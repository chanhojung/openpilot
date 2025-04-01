from opendbc.car import Bus, get_safety_config, structs
from opendbc.car.hyundai.hyundaicanfd import CanBus
from opendbc.car.hyundai.values import HyundaiFlags, CAR, DBC, \
                                                   CANFD_UNSUPPORTED_LONGITUDINAL_CAR, \
                                                   UNSUPPORTED_LONGITUDINAL_CAR, HyundaiSafetyFlags
from opendbc.car.hyundai.radar_interface import RADAR_START_ADDR
from opendbc.car.interfaces import CarInterfaceBase
from opendbc.car.disable_ecu import disable_ecu
from opendbc.car.hyundai.carcontroller import CarController
from opendbc.car.hyundai.carstate import CarState
from opendbc.car.hyundai.radar_interface import RadarInterface

ButtonType = structs.CarState.ButtonEvent.Type

from opendbc.car.hyundai.cruise_helper import enable_radar_tracks #ajouatom
from opendbc.car.hyundai.tunes import LatTunes, set_lat_tune
from openpilot.common.params import Params
from decimal import Decimal

Ecu = structs.CarParams.Ecu
SteerControlType = structs.CarParams.SteerControlType
# Cancel button can sometimes be ACC pause/resume button, main button can also enable on some cars
ENABLE_BUTTONS = (ButtonType.accelCruise, ButtonType.decelCruise, ButtonType.cancel, ButtonType.mainCruise, ButtonType.lfa)


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, experimental_long, docs) -> structs.CarParams:
    ret.brand = "hyundai"

    cam_can = CanBus(None, fingerprint).CAM
    lka_steering = 0x50 in fingerprint[cam_can] or 0x110 in fingerprint[cam_can]
    CAN = CanBus(None, fingerprint, lka_steering)

    params = Params()

    kisaLongAlt = int(params.get("KISALongAlt", encoding="utf8"))

    if ret.flags & HyundaiFlags.CANFD:
      # Shared configuration for CAN-FD cars
      ret.experimentalLongitudinalAvailable = candidate not in CANFD_UNSUPPORTED_LONGITUDINAL_CAR
      if lka_steering and Ecu.adas not in [fw.ecu for fw in car_fw]:
        # this needs to be figured out for cars without an ADAS ECU
        ret.experimentalLongitudinalAvailable = False

      ret.isCanFD = True
      ret.enableBsm = 0x1e5 in fingerprint[CAN.ECAN]
      ret.sccBus = 0
      ret.bsmAvailable = False
      ret.lfaAvailable = False
      ret.lvrAvailable = False
      ret.evgearAvailable = False
      ret.emsAvailable = False
      ret.autoHoldAvailable = 0x60 in fingerprint[CAN.ECAN]
      ret.lfaHdaAvailable = False
      ret.navAvailable = False
      ret.adrvAvailable = (lka_steering and 0x200 in fingerprint[CAN.ECAN]) or 0x200 in fingerprint[cam_can]
      ret.brakeAvailable = 0x65 in fingerprint[CAN.ECAN]
      ret.tpmsAvailable = 0x3a0 in fingerprint[CAN.ECAN]
      ret.isAngleControl = 0xcb in fingerprint[CAN.ECAN] or 0xcb in fingerprint[CAN.ACAN] or 0xcb in fingerprint[cam_can]

      # Check if the car is hybrid. Only HEV/PHEV cars have 0xFA on E-CAN.
      if 0xFA in fingerprint[CAN.ECAN]:
        ret.flags |= HyundaiFlags.HYBRID.value

      if lka_steering:
        # detect LKA steering
        ret.flags |= HyundaiFlags.CANFD_LKA_STEERING.value
        if 0x110 in fingerprint[CAN.CAM]:
          ret.flags |= HyundaiFlags.CANFD_LKA_STEERING_ALT.value
      else:
        # no LKA steering
        if 0x1cf not in fingerprint[CAN.ECAN]:
          ret.flags |= HyundaiFlags.CANFD_ALT_BUTTONS.value
        if not ret.flags & HyundaiFlags.RADAR_SCC:
          ret.flags |= HyundaiFlags.CANFD_CAMERA_SCC.value

      # Some LKA steering cars have alternative messages for gear checks
      # ICE cars do not have 0x130; GEARS message on 0x40 or 0x70 instead
      if 0x130 not in fingerprint[CAN.ECAN]:
        if 0x40 not in fingerprint[CAN.ECAN]:
          ret.flags |= HyundaiFlags.CANFD_ALT_GEARS_2.value
        else:
          ret.flags |= HyundaiFlags.CANFD_ALT_GEARS.value

      cfgs = [get_safety_config(structs.CarParams.SafetyModel.hyundaiCanfd), ]
      if CAN.ECAN >= 4:
        cfgs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
      ret.safetyConfigs = cfgs

      if ret.flags & HyundaiFlags.CANFD_LKA_STEERING:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_LKA_STEERING.value
        if ret.flags & HyundaiFlags.CANFD_LKA_STEERING_ALT:
          ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_LKA_STEERING_ALT.value
      if ret.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_ALT_BUTTONS.value
      if ret.flags & HyundaiFlags.CANFD_CAMERA_SCC:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CAMERA_SCC.value
      if params.get_bool("LFAButtonEngagement"):
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.KISA_COMMUNITY.value
    else:
      ret.isCanFD = False
      # Shared configuration for non CAN-FD cars
      ret.experimentalLongitudinalAvailable = candidate not in UNSUPPORTED_LONGITUDINAL_CAR
      ret.enableBsm = 0x58b in fingerprint[0]
      ret.sccBus = 2 if kisaLongAlt and not params.get_bool("ExperimentalLongitudinalEnabled") else 0
      ret.bsmAvailable = 1419 in fingerprint[0]
      ret.lfaAvailable = 1157 in fingerprint[2]
      ret.lvrAvailable = 872 in fingerprint[0]
      ret.evgearAvailable = 882 in fingerprint[0]
      ret.emsAvailable = 870 in fingerprint[0]
      ret.autoHoldAvailable = 1151 in fingerprint[0]
      ret.lfaHdaAvailable = 1157 in fingerprint[0]
      ret.navAvailable = 1348 in fingerprint[0]
      ret.adrvAvailable = False
      ret.tpmsAvailable = 1427 in fingerprint[0]
      ret.isAngleControl = False
      ret.evInfo = 1291 in fingerprint[0]

      # Send LFA message on cars with HDA
      if 0x485 in fingerprint[2]:
        ret.flags |= HyundaiFlags.SEND_LFA.value

      # These cars use the FCA11 message for the AEB and FCW signals, all others use SCC12
      if 0x38d in fingerprint[0] or 0x38d in fingerprint[2]:
        ret.flags |= HyundaiFlags.USE_FCA.value

      if ret.flags & HyundaiFlags.LEGACY:
        # these cars require a special panda safety mode due to missing counters and checksums in the messages
        ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.hyundaiLegacy)]
      else:
        ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.hyundai, 0)]

      if ret.sccBus == 2:
        ret.scc13Available = 1290 in fingerprint[0] or 1290 in fingerprint[2]
        ret.scc14Available = 905 in fingerprint[0] or 905 in fingerprint[2]
        ret.openpilotLongitudinalControl = True
        ret.radarUnavailable = False
        ret.pcmCruise = True
      else:
        ret.pcmCruise = not ret.openpilotLongitudinalControl

      if ret.flags & HyundaiFlags.CAMERA_SCC or ret.sccBus == 2:
        ret.safetyConfigs[0].safetyParam |= HyundaiSafetyFlags.CAMERA_SCC.value

      # These cars have the LFA button on the steering wheel
      if 0x391 in fingerprint[0]:
        ret.flags |= HyundaiFlags.HAS_LDA_BUTTON.value
      if params.get_bool("UFCModeEnabled"):
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.KISA_COMMUNITY.value

    # Common lateral control setup

    ret.centerToFront = ret.wheelbase * 0.4
    ret.steerActuatorDelay = float(Decimal(params.get("SteerActuatorDelayAdj", encoding="utf8")) * Decimal('0.01'))   #0.1
    ret.steerLimitTimer = float(Decimal(params.get("SteerLimitTimerAdj", encoding="utf8")) * Decimal('0.01'))   #0.4

    ret.smoothSteer.method = int( params.get("KisaSteerMethod", encoding="utf8") )   # 1
    ret.smoothSteer.maxSteeringAngle = float( params.get("KisaMaxSteeringAngle", encoding="utf8") )   # 90
    ret.smoothSteer.maxDriverAngleWait = float( params.get("KisaMaxDriverAngleWait", encoding="utf8") )  # 0.002
    ret.smoothSteer.maxSteerAngleWait = float( params.get("KisaMaxSteerAngleWait", encoding="utf8") )   # 0.001  # 10 sec
    ret.smoothSteer.driverAngleWait = float( params.get("KisaDriverAngleWait", encoding="utf8") )  #0.001

    ret.experimentalLong = params.get_bool("ExperimentalLongitudinalEnabled")
    
    if ret.isAngleControl:    
      ret.steerControlType = SteerControlType.angle
    else:
      lat_control_method = int(params.get("LateralControlMethod", encoding="utf8"))
      if lat_control_method == 0:
        set_lat_tune(ret.lateralTuning, LatTunes.PID)
      elif lat_control_method == 1:
        set_lat_tune(ret.lateralTuning, LatTunes.INDI)
      elif lat_control_method == 2:
        set_lat_tune(ret.lateralTuning, LatTunes.LQR)
      elif lat_control_method == 3:
        #set_lat_tune(ret.lateralTuning, LatTunes.TORQUE)
        CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      elif lat_control_method == 4:
        set_lat_tune(ret.lateralTuning, LatTunes.ATOM)    # Hybrid tune

    # Common longitudinal control setup

    ret.radarUnavailable = RADAR_START_ADDR not in fingerprint[1] or Bus.radar not in DBC[ret.carFingerprint]
    ret.openpilotLongitudinalControl = experimental_long and ret.experimentalLongitudinalAvailable
    ret.pcmCruise = not ret.openpilotLongitudinalControl
    ret.startingState = True
    ret.vEgoStarting = 0.1
    ret.startAccel = 1.0
    ret.longitudinalActuatorDelay = 0.5

    if (ret.openpilotLongitudinalControl and not kisaLongAlt) or params.get_bool("ExperimentalLongitudinalEnabled"):
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.LONG.value
    if ret.flags & HyundaiFlags.HYBRID:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.HYBRID_GAS.value
    elif ret.flags & HyundaiFlags.EV:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.EV_GAS.value
    elif ret.flags & HyundaiFlags.FCEV:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.FCEV_GAS.value

    # Car specific configuration overrides

    if candidate == CAR.KIA_OPTIMA_G4_FL:
      ret.steerActuatorDelay = 0.2

    ret.dashcamOnly = False

    return ret

  @staticmethod
  def init(CP, can_recv, can_send):
    if CP.openpilotLongitudinalControl and not (CP.flags & (HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CAMERA_SCC)):
      addr, bus = 0x7d0, CanBus(CP).ECAN if CP.flags & HyundaiFlags.CANFD else 0
      if CP.flags & HyundaiFlags.CANFD_LKA_STEERING.value:
        addr, bus = 0x730, CanBus(CP).ECAN
      disable_ecu(can_recv, can_send, bus=bus, addr=addr, com_cont_req=b'\x28\x83\x01')
      enable_radar_tracks(CP, can_recv, can_send) # from ajouatom. really appreciate that.

    # for blinkers
    if CP.flags & HyundaiFlags.ENABLE_BLINKERS:
      disable_ecu(can_recv, can_send, bus=CanBus(CP).ECAN, addr=0x7B1, com_cont_req=b'\x28\x83\x01')
