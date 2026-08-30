import unittest

from trading_system.live_controller import desired_action


class LiveControllerTests(unittest.TestCase):
    def test_enters_only_without_existing_position(self) -> None:
        self.assertEqual(desired_action(1, False, False), "buy")
        self.assertEqual(desired_action(1, True, False), "hold")

    def test_exits_only_managed_position(self) -> None:
        self.assertEqual(desired_action(0, True, True), "sell")
        self.assertEqual(desired_action(0, True, False), "hold")

    def test_never_reenters_recorded_managed_position(self) -> None:
        self.assertEqual(desired_action(1, False, True), "hold")


if __name__ == "__main__":
    unittest.main()
