import math
import numpy as np
from common.numpy_fast import clip, interp
from common.realtime import sec_since_boot
from selfdrive.modeld.constants import T_IDXS
from selfdrive.controls.lib.radar_helpers import _LEAD_ACCEL_TAU
from selfdrive.controls.lib.lead_mpc_lib import libmpc_py
from selfdrive.controls.lib.drive_helpers import MPC_COST_LONG, CONTROL_N
from selfdrive.swaglog import cloudlog
from common.params import Params
from decimal import Decimal

MPC_T = list(np.arange(0,1.,.2)) + list(np.arange(1.,10.6,.6))


class LeadMpc():
  def __init__(self, mpc_id):
    self.lead_id = mpc_id

    self.reset_mpc()
    self.prev_lead_status = False
    self.prev_lead_x = 0.0
    self.new_lead = False

    self.last_cloudlog_t = 0.0
    self.n_its = 0
    self.duration = 0
    self.status = False

    self.cruise_gap1 = float(Decimal(Params().get("CruiseGap1", encoding="utf8")) * Decimal('0.1'))
    self.cruise_gap2 = float(Decimal(Params().get("CruiseGap2", encoding="utf8")) * Decimal('0.1'))
    self.cruise_gap3 = float(Decimal(Params().get("CruiseGap3", encoding="utf8")) * Decimal('0.1'))
    self.cruise_gap4 = float(Decimal(Params().get("CruiseGap4", encoding="utf8")) * Decimal('0.1'))

    self.dynamic_TR = int(Params().get("DynamicTR", encoding="utf8"))

  def reset_mpc(self):
    ffi, self.libmpc = libmpc_py.get_libmpc(self.lead_id)
    self.libmpc.init(MPC_COST_LONG.TTC, MPC_COST_LONG.DISTANCE,
                     MPC_COST_LONG.ACCELERATION, MPC_COST_LONG.JERK)

    self.mpc_solution = ffi.new("log_t *")
    self.cur_state = ffi.new("state_t *")
    self.cur_state[0].v_ego = 0
    self.cur_state[0].a_ego = 0
    self.a_lead_tau = _LEAD_ACCEL_TAU

  def set_cur_state(self, v, a):
    v_safe = max(v, 1e-3)
    a_safe = a
    self.cur_state[0].v_ego = v_safe
    self.cur_state[0].a_ego = a_safe

  def update(self, CS, radarstate, v_cruise):
    v_ego = CS.vEgo
    if self.lead_id == 0:
      lead = radarstate.leadOne
    else:
      lead = radarstate.leadOne
    self.status = lead.status and lead.modelProb > .5

    # Setup current mpc state
    self.cur_state[0].x_ego = 0.0

    if lead is not None and lead.status:
      x_lead = lead.dRel
      v_lead = max(0.0, lead.vLead)
      a_lead = lead.aLeadK

      if (v_lead < 0.1 or -a_lead / 2.0 > v_lead):
        v_lead = 0.0
        a_lead = 0.0

      self.a_lead_tau = lead.aLeadTau
      self.new_lead = False
      if not self.prev_lead_status or abs(x_lead - self.prev_lead_x) > 2.5:
        self.libmpc.init_with_simulation(v_ego, x_lead, v_lead, a_lead, self.a_lead_tau)
        self.new_lead = True

      self.prev_lead_status = True
      self.prev_lead_x = x_lead
      self.cur_state[0].x_l = x_lead
      self.cur_state[0].v_l = v_lead
    else:
      self.prev_lead_status = False
      # Fake a fast lead car, so mpc keeps running
      self.cur_state[0].x_l = 50.0
      self.cur_state[0].v_l = v_ego + 10.0
      a_lead = 0.0
      self.a_lead_tau = _LEAD_ACCEL_TAU

    # neokii value, opkr mod
    cruise_gap = int(clip(CS.cruiseGapSet, 1., 4.))
    dynamic_TR = interp(v_ego*3.6, [0, 20, 40, 60, 110], [1.0, 1.3, 1.5, 1.7, 2.0] )
    TR = interp(float(cruise_gap), [1., 2., 3., 4.], [self.cruise_gap1, self.cruise_gap2, self.cruise_gap3, self.cruise_gap4])
    if self.dynamic_TR == 1:
      TR = interp(float(cruise_gap), [1., 2., 3., 4.], [dynamic_TR, self.cruise_gap2, self.cruise_gap3, self.cruise_gap4])
    elif self.dynamic_TR == 2:
      TR = interp(float(cruise_gap), [1., 2., 3., 4.], [self.cruise_gap1, dynamic_TR, self.cruise_gap3, self.cruise_gap4])
    elif self.dynamic_TR == 3:
      TR = interp(float(cruise_gap), [1., 2., 3., 4.], [self.cruise_gap1, self.cruise_gap2, dynamic_TR, self.cruise_gap4])
    elif self.dynamic_TR == 4:
      TR = interp(float(cruise_gap), [1., 2., 3., 4.], [self.cruise_gap1, self.cruise_gap2, self.cruise_gap3, dynamic_TR])


    # Calculate mpc
    t = sec_since_boot()
    self.n_its = self.libmpc.run_mpc(self.cur_state, self.mpc_solution, self.a_lead_tau, a_lead, TR)
    self.v_solution = interp(T_IDXS[:CONTROL_N], MPC_T, self.mpc_solution.v_ego)
    self.a_solution = interp(T_IDXS[:CONTROL_N], MPC_T, self.mpc_solution.a_ego)
    self.duration = int((sec_since_boot() - t) * 1e9)

    # Reset if NaN or goes through lead car
    crashing = any(lead - ego < -50 for (lead, ego) in zip(self.mpc_solution[0].x_l, self.mpc_solution[0].x_ego))
    nans = any(math.isnan(x) for x in self.mpc_solution[0].v_ego)
    backwards = min(self.mpc_solution[0].v_ego) < -0.01

    if ((backwards or crashing) and self.prev_lead_status) or nans:
      if t > self.last_cloudlog_t + 5.0:
        self.last_cloudlog_t = t
        cloudlog.warning("Longitudinal mpc %d reset - backwards: %s crashing: %s nan: %s" % (
                          self.lead_id, backwards, crashing, nans))

      self.libmpc.init(MPC_COST_LONG.TTC, MPC_COST_LONG.DISTANCE,
                       MPC_COST_LONG.ACCELERATION, MPC_COST_LONG.JERK)
      self.cur_state[0].v_ego = v_ego
      self.cur_state[0].a_ego = 0.0
      self.a_mpc = CS.aEgo
      self.prev_lead_status = False
