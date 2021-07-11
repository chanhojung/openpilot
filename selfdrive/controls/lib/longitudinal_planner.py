#!/usr/bin/env python3
import math
import numpy as np
from common.params import Params
from common.numpy_fast import interp

import cereal.messaging as messaging
from cereal import log
from common.realtime import DT_MDL
from common.realtime import sec_since_boot
from selfdrive.modeld.constants import T_IDXS
from selfdrive.config import Conversions as CV
from selfdrive.controls.lib.fcw import FCWChecker
from selfdrive.controls.lib.longcontrol import LongCtrlState
from selfdrive.controls.lib.lead_mpc import LeadMpc
from selfdrive.controls.lib.long_mpc import LongitudinalMpc
from selfdrive.controls.lib.drive_helpers import V_CRUISE_MAX, CONTROL_N
from selfdrive.swaglog import cloudlog

LON_MPC_STEP = 0.2  # first step is 0.2s
AWARENESS_DECEL = -0.2     # car smoothly decel at .2m/s^2 when user is distracted
A_CRUISE_MIN = -1.2
A_CRUISE_MAX = 1.2

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]


def limit_accel_in_turns(v_ego, angle_steers, a_target, CP):
  """
  This function returns a limited long acceleration allowed, depending on the existing lateral acceleration
  this should avoid accelerating when losing the target in turns
  """

  a_total_max = interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
  a_y = v_ego**2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
  a_x_allowed = math.sqrt(max(a_total_max**2 - a_y**2, 0.))

  return [a_target[0], min(a_target[1], a_x_allowed)]


class Planner():
  def __init__(self, CP):
    self.CP = CP
    self.mpcs = {}
    self.mpcs['lead0'] = LeadMpc(0)
    self.mpcs['lead1'] = LeadMpc(1)
    self.mpcs['cruise'] = LongitudinalMpc()

    self.fcw = False
    self.fcw_checker = FCWChecker()

    self.v_desired = 0.0
    self.a_desired = 0.0
    self.longitudinalPlanSource = 'cruise'
    self.alpha = np.exp(-DT_MDL/2.0)
    self.lead_0 = log.ModelDataV2.LeadDataV3.new_message()
    self.lead_1 = log.ModelDataV2.LeadDataV3.new_message()

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)

    self.params = Params()

    self.target_speed_map = 0
    self.target_speed_map_dist = 0
    self.target_speed_map_dist_prev = 0
    self.target_speed_map_block = False
    self.target_speed_map_sign = False
    self.map_sign = 0
    self.vego = 0
    self.second = 0
    self.map_enabled = False

  def update(self, sm, CP):
    cur_time = sec_since_boot()
    v_ego = sm['carState'].vEgo
    a_ego = sm['carState'].aEgo
    self.vego = v_ego

    # if sm['controlsState'].mapSign == 124:
    #   v_cruise_kph = 20.
    if CP.sccBus != 0:
      v_cruise_kph = sm['carState'].vSetDis
    else:
      v_cruise_kph = sm['controlsState'].vCruise
    v_cruise_kph = min(v_cruise_kph, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS

    long_control_state = sm['controlsState'].longControlState
    force_slow_decel = sm['controlsState'].forceDecel

    self.lead_0 = sm['radarState'].leadOne
    self.lead_1 = sm['radarState'].leadTwo

    enabled = (long_control_state == LongCtrlState.pid) or (long_control_state == LongCtrlState.stopping)
    if not enabled or sm['carState'].gasPressed:
      self.v_desired = v_ego
      self.a_desired = a_ego

    # Prevent divergence, smooth in current v_ego
    self.v_desired = self.alpha * self.v_desired + (1 - self.alpha) * v_ego
    self.v_desired = max(0.0, self.v_desired)

    accel_limits = [A_CRUISE_MIN, A_CRUISE_MAX]
    accel_limits_turns = limit_accel_in_turns(v_ego, sm['carState'].steeringAngleDeg, accel_limits, self.CP)
    if force_slow_decel and False: # awareness decel is disabled for now:
      # if required so, force a smooth deceleration
      accel_limits_turns[1] = min(accel_limits_turns[1], AWARENESS_DECEL)
      accel_limits_turns[0] = min(accel_limits_turns[0], accel_limits_turns[1])
    # clip limits, cannot init MPC outside of bounds
    accel_limits_turns[0] = min(accel_limits_turns[0], self.a_desired)
    accel_limits_turns[1] = max(accel_limits_turns[1], self.a_desired)
    self.mpcs['cruise'].set_accel_limits(accel_limits_turns[0], accel_limits_turns[1])

    next_a = np.inf
    for key in self.mpcs:
      self.mpcs[key].set_cur_state(self.v_desired, self.a_desired)
      self.mpcs[key].update(sm['carState'], sm['radarState'], v_cruise)
      if self.mpcs[key].status and self.mpcs[key].a_solution[5] < next_a:
        self.longitudinalPlanSource = key
        self.v_desired_trajectory = self.mpcs[key].v_solution[:CONTROL_N]
        self.a_desired_trajectory = self.mpcs[key].a_solution[:CONTROL_N]
        next_a = self.mpcs[key].a_solution[5]

    # determine fcw
    if self.mpcs['lead0'].new_lead:
      self.fcw_checker.reset_lead(cur_time)
    blinkers = sm['carState'].leftBlinker or sm['carState'].rightBlinker
    self.fcw = self.fcw_checker.update(self.mpcs['lead0'].mpc_solution, cur_time,
                                       sm['controlsState'].active,
                                       v_ego, sm['carState'].aEgo,
                                       self.lead_1.dRel, self.lead_1.vLead, self.lead_1.aLeadK,
                                       self.lead_1.yRel, self.lead_1.vLat,
                                       self.lead_1.fcw, blinkers) and not sm['carState'].brakePressed
    if self.fcw:
      cloudlog.info("FCW triggered %s", self.fcw_checker.counters)

    # Interpolate 0.05 seconds and save as starting point for next iteration
    a_prev = self.a_desired
    self.a_desired = np.interp(DT_MDL, T_IDXS[:CONTROL_N], self.a_desired_trajectory)
    self.v_desired = self.v_desired + DT_MDL * (self.a_desired + a_prev)/2.0

    # opkr
    self.second += 1
    if self.second > 30:
      self.map_enabled = self.params.get_bool("OpkrMapEnable")
      self.second = 0
    if self.map_enabled and v_ego > 0.3:
      self.map_sign = sm['liveMapData'].safetySign
      self.target_speed_map_dist = sm['liveMapData'].speedLimitDistance
      if self.target_speed_map_dist_prev != self.target_speed_map_dist:
        self.target_speed_map_dist_prev = self.target_speed_map_dist
        self.target_speed_map = sm['liveMapData'].speedLimit
        if self.target_speed_map > 29:
          if self.target_speed_map_dist > 1250:
            self.target_speed_map_block = True
        else:
          self.target_speed_map_block = False

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_alive_and_valid(service_list=['carState', 'controlsState'])

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']

    longitudinalPlan.speeds = [float(x) for x in self.v_desired_trajectory]
    longitudinalPlan.accels = [float(x) for x in self.a_desired_trajectory]

    longitudinalPlan.hasLead = self.mpcs['lead0'].status
    longitudinalPlan.longitudinalPlanSource = self.longitudinalPlanSource
    longitudinalPlan.fcw = self.fcw

    # Send radarstate(dRel, vRel, yRel)
    lead_1 = sm['radarState'].leadOne
    lead_2 = sm['radarState'].leadTwo
    longitudinalPlan.dRel1 = float(lead_1.dRel)
    longitudinalPlan.yRel1 = float(lead_1.yRel)
    longitudinalPlan.vRel1 = float(lead_1.vRel)
    longitudinalPlan.dRel2 = float(lead_2.dRel)
    longitudinalPlan.yRel2 = float(lead_2.yRel)
    longitudinalPlan.vRel2 = float(lead_2.vRel)
    longitudinalPlan.status2 = bool(lead_2.status)
    if self.map_enabled:
      longitudinalPlan.mapSign = float(self.map_sign)
      cam_distance_calc = 0
      cam_distance_calc = interp(self.vego*CV.MS_TO_KPH, [30,110], [2.5,4])  # 감속 기본 거리
      consider_speed = interp((self.vego*CV.MS_TO_KPH - self.target_speed_map), [0,40], [1, 2]) # 속도차에 따른 거리 추가
      if self.target_speed_map > 29 and self.target_speed_map_sign:
        longitudinalPlan.targetSpeedCamera = float(self.target_speed_map)
        longitudinalPlan.targetSpeedCameraDist = float(self.target_speed_map_dist)
        longitudinalPlan.onSpeedControl = True
      elif self.target_speed_map > 29 and self.target_speed_map_dist < cam_distance_calc*consider_speed*self.vego*CV.MS_TO_KPH:
        longitudinalPlan.targetSpeedCamera = float(self.target_speed_map)
        longitudinalPlan.targetSpeedCameraDist = float(self.target_speed_map_dist)
        longitudinalPlan.onSpeedControl = True
        self.target_speed_map_sign = True
      elif self.target_speed_map > 29 and self.target_speed_map_dist >= cam_distance_calc*consider_speed*self.vego*CV.MS_TO_KPH and self.target_speed_map_block:
        longitudinalPlan.targetSpeedCamera = float(self.target_speed_map)
        longitudinalPlan.targetSpeedCameraDist = float(self.target_speed_map_dist)
        longitudinalPlan.onSpeedControl = True
        self.target_speed_map_sign = True
      elif self.target_speed_map > 29 and self.target_speed_map_dist < 600.:
        longitudinalPlan.targetSpeedCamera = float(self.target_speed_map)
        longitudinalPlan.targetSpeedCameraDist = float(self.target_speed_map_dist)
        longitudinalPlan.onSpeedControl = False
      elif self.target_speed_map == 0 and self.target_speed_map_dist != 0.:
        longitudinalPlan.targetSpeedCamera = float(self.target_speed_map)
        longitudinalPlan.targetSpeedCameraDist = float(self.target_speed_map_dist)
        longitudinalPlan.onSpeedControl = False
        self.target_speed_map_sign = False
      else:
        longitudinalPlan.targetSpeedCamera = 0
        longitudinalPlan.targetSpeedCameraDist = 0
        longitudinalPlan.onSpeedControl = False
        self.target_speed_map_sign = False

    pm.send('longitudinalPlan', plan_send)
