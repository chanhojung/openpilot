#!/usr/bin/env python3
import unittest
from typing import Dict, List
from panda import Panda
from panda.tests.safety import libpandasafety_py
import panda.tests.safety.common as common
from panda.tests.safety.common import CANPackerPanda, ALTERNATIVE_EXPERIENCE

MAX_BRAKE = 400
MAX_GAS = 3072
MAX_REGEN = 1404
INACTIVE_REGEN = 1404


class Buttons:
  UNPRESS = 1
  RES_ACCEL = 2
  DECEL_SET = 3
  CANCEL = 6


class TestGmSafetyBase(common.PandaSafetyTest, common.DriverTorqueSteeringSafetyTest):
  STANDSTILL_THRESHOLD = 10 * 0.0311
  RELAY_MALFUNCTION_ADDR = 384
  RELAY_MALFUNCTION_BUS = 0
  BUTTONS_BUS = 0

  MAX_RATE_UP = 7
  MAX_RATE_DOWN = 17
  MAX_TORQUE = 300
  MAX_RT_DELTA = 128
  RT_INTERVAL = 250000
  DRIVER_TORQUE_ALLOWANCE = 50
  DRIVER_TORQUE_FACTOR = 4

  @classmethod
  def setUpClass(cls):
    if cls.__name__ == "TestGmSafetyBase":
      cls.packer = None
      cls.safety = None
      raise unittest.SkipTest

  def setUp(self):
    self.packer = CANPackerPanda("gm_global_a_powertrain_generated")
    self.packer_chassis = CANPackerPanda("gm_global_a_chassis")
    self.safety = libpandasafety_py.libpandasafety
    self.safety.set_safety_hooks(Panda.SAFETY_GM, 0)
    self.safety.init_tests()

  def _pcm_status_msg(self, enable):
    raise NotImplementedError

  def _speed_msg(self, speed):
    values = {"%sWheelSpd" % s: speed for s in ["RL", "RR"]}
    return self.packer.make_can_msg_panda("EBCMWheelSpdRear", 0, values)

  def _user_brake_msg(self, brake):
    # GM safety has a brake threshold of 8
    values = {"BrakePedalPos": 8 if brake else 0}
    return self.packer.make_can_msg_panda("ECMAcceleratorPos", 0, values)

  def _user_regen_msg(self, regen):
    values = {"RegenPaddle": 2 if regen else 0}
    return self.packer.make_can_msg_panda("EBCMRegenPaddle", 0, values)

  def _user_gas_msg(self, gas):
    values = {"AcceleratorPedal2": 1 if gas else 0}
    return self.packer.make_can_msg_panda("AcceleratorPedal2", 0, values)

  def _send_brake_msg(self, brake):
    values = {"FrictionBrakeCmd": -brake}
    return self.packer_chassis.make_can_msg_panda("EBCMFrictionBrakeCmd", 2, values)

  def _send_gas_msg(self, gas):
    values = {"GasRegenCmd": gas}
    return self.packer.make_can_msg_panda("ASCMGasRegenCmd", 0, values)

  def _torque_driver_msg(self, torque):
    values = {"LKADriverAppldTrq": torque}
    return self.packer.make_can_msg_panda("PSCMStatus", 0, values)

  def _torque_cmd_msg(self, torque, steer_req=1):
    values = {"LKASteeringCmd": torque}
    return self.packer.make_can_msg_panda("ASCMLKASteeringCmd", 0, values)

  def _button_msg(self, buttons):
    values = {"ACCButtons": buttons}
    return self.packer.make_can_msg_panda("ASCMSteeringButton", self.BUTTONS_BUS, values)

  def test_brake_safety_check(self, stock_longitudinal=False):
    for enabled in [0, 1]:
      for b in range(0, 500):
        self.safety.set_controls_allowed(enabled)
        if abs(b) > MAX_BRAKE or (not enabled and b != 0) or stock_longitudinal:
          self.assertFalse(self._tx(self._send_brake_msg(b)))
        else:
          self.assertTrue(self._tx(self._send_brake_msg(b)))

  def test_gas_safety_check(self, stock_longitudinal=False):
    # Block if enabled and out of actuation range, disabled and not inactive regen, or if stock longitudinal
    for enabled in [0, 1]:
      for gas_regen in range(0, 2 ** 12 - 1):
        self.safety.set_controls_allowed(enabled)
        should_tx = (((enabled and MAX_REGEN <= gas_regen <= MAX_GAS) or
                      (not enabled and gas_regen == INACTIVE_REGEN)) and not stock_longitudinal)
        self.assertEqual(should_tx, self._tx(self._send_gas_msg(gas_regen)), (enabled, gas_regen))

  def test_tx_hook_on_pedal_pressed(self):
    for pedal in ['brake', 'gas']:
      if pedal == 'brake':
        # brake_pressed_prev and vehicle_moving
        self._rx(self._speed_msg(100))
        self._rx(self._user_brake_msg(1))
      elif pedal == 'gas':
        # gas_pressed_prev
        self._rx(self._user_gas_msg(MAX_GAS))

      self.safety.set_controls_allowed(1)
      self.assertFalse(self._tx(self._send_brake_msg(MAX_BRAKE)))
      self.assertFalse(self._tx(self._torque_cmd_msg(self.MAX_RATE_UP)))
      self.assertFalse(self._tx(self._send_gas_msg(MAX_GAS)))

      # reset status
      self.safety.set_controls_allowed(0)
      self._tx(self._send_brake_msg(0))
      self._tx(self._torque_cmd_msg(0))
      if pedal == 'brake':
        self._rx(self._speed_msg(0))
        self._rx(self._user_brake_msg(0))
      elif pedal == 'gas':
        self._rx(self._user_gas_msg(0))

  def test_tx_hook_on_pedal_pressed_on_alternative_gas_experience(self):
    for pedal in ['brake', 'gas']:
      self.safety.set_alternative_experience(ALTERNATIVE_EXPERIENCE.DISABLE_DISENGAGE_ON_GAS)
      if pedal == 'brake':
        # brake_pressed_prev and vehicle_moving
        self._rx(self._speed_msg(100))
        self._rx(self._user_brake_msg(1))
        allow_ctrl = False
      elif pedal == 'gas':
        # gas_pressed_prev
        self._rx(self._user_gas_msg(MAX_GAS))
        allow_ctrl = True

      # Test we allow lateral on gas press, but never longitudinal
      self.safety.set_controls_allowed(1)
      self.assertEqual(allow_ctrl, self._tx(self._torque_cmd_msg(self.MAX_RATE_UP)))
      self.assertFalse(self._tx(self._send_brake_msg(MAX_BRAKE)))
      self.assertFalse(self._tx(self._send_gas_msg(MAX_GAS)))

      # reset status
      if pedal == 'brake':
        self._rx(self._speed_msg(0))
        self._rx(self._user_brake_msg(0))
      elif pedal == 'gas':
        self._rx(self._user_gas_msg(0))


class TestGmAscmSafety(TestGmSafetyBase):
  TX_MSGS = [[384, 0], [1033, 0], [1034, 0], [715, 0], [880, 0],  # pt bus
             [161, 1], [774, 1], [776, 1], [784, 1],  # obs bus
             [789, 2],  # ch bus
             [0x104c006c, 3], [0x10400060, 3]]  # gmlan
  FWD_BLACKLISTED_ADDRS: Dict[int, List[int]] = {}
  FWD_BUS_LOOKUP: Dict[int, int] = {}

  def setUp(self):
    self.packer = CANPackerPanda("gm_global_a_powertrain_generated")
    self.packer_chassis = CANPackerPanda("gm_global_a_chassis")
    self.safety = libpandasafety_py.libpandasafety
    self.safety.set_safety_hooks(Panda.SAFETY_GM, 0)
    self.safety.init_tests()

  # override these tests from PandaSafetyTest, ASCM GM uses button enable
  def test_disable_control_allowed_from_cruise(self):
    pass

  def test_enable_control_allowed_from_cruise(self):
    pass

  def test_cruise_engaged_prev(self):
    pass

  def _pcm_status_msg(self, enable):
    raise NotImplementedError

  def test_set_resume_buttons(self):
    """
      SET and RESUME enter controls allowed on their falling edge.
    """
    for btn in range(8):
      self.safety.set_controls_allowed(0)
      for _ in range(10):
        self._rx(self._button_msg(btn))
        self.assertFalse(self.safety.get_controls_allowed())

      # should enter controls allowed on falling edge
      if btn in (Buttons.RES_ACCEL, Buttons.DECEL_SET):
        self._rx(self._button_msg(Buttons.UNPRESS))
        self.assertTrue(self.safety.get_controls_allowed())

  def test_cancel_button(self):
    self.safety.set_controls_allowed(1)
    self._rx(self._button_msg(Buttons.CANCEL))
    self.assertFalse(self.safety.get_controls_allowed())


class TestGmCameraSafety(TestGmSafetyBase):
  TX_MSGS = [[384, 0],  # pt bus
             [388, 2]]  # camera bus
  FWD_BLACKLISTED_ADDRS = {2: [384], 0: [388]}  # block LKAS message and PSCMStatus
  FWD_BUS_LOOKUP = {0: 2, 2: 0}
  BUTTONS_BUS = 2  # tx only

  def setUp(self):
    self.packer = CANPackerPanda("gm_global_a_powertrain_generated")
    self.packer_chassis = CANPackerPanda("gm_global_a_chassis")
    self.safety = libpandasafety_py.libpandasafety
    self.safety.set_safety_hooks(Panda.SAFETY_GM, Panda.FLAG_GM_HW_CAM)
    self.safety.init_tests()

  def _user_gas_msg(self, gas):
    cruise_active = self.safety.get_controls_allowed()
    values = {"AcceleratorPedal2": 1 if gas else 0, "CruiseState": cruise_active}
    return self.packer.make_can_msg_panda("AcceleratorPedal2", 0, values)

  def _pcm_status_msg(self, enable):
    values = {"CruiseState": enable}
    return self.packer.make_can_msg_panda("AcceleratorPedal2", 0, values)

  def test_buttons(self):
    # Only CANCEL button is allowed while cruise is enabled
    self.safety.set_controls_allowed(0)
    for btn in range(8):
      self.assertFalse(self._tx(self._button_msg(btn)))

    self.safety.set_controls_allowed(1)
    for btn in range(8):
      self.assertFalse(self._tx(self._button_msg(btn)))

    for enabled in (True, False):
      self._rx(self._pcm_status_msg(enabled))
      self.assertEqual(enabled, self._tx(self._button_msg(Buttons.CANCEL)))

  # Uses stock longitudinal, allow no longitudinal actuation
  def test_brake_safety_check(self, stock_longitudinal=True):
    super().test_brake_safety_check(stock_longitudinal=stock_longitudinal)

  def test_gas_safety_check(self, stock_longitudinal=True):
    super().test_gas_safety_check(stock_longitudinal=stock_longitudinal)


if __name__ == "__main__":
  unittest.main()
