import unittest

from aiagent.permission_policy import PermissionPolicy


class PermissionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PermissionPolicy()

    def test_low_risk_is_allowed(self):
        decision = self.policy.decide("calculator", "low")

        self.assertEqual(decision.action, "allow")

    def test_medium_risk_requires_approval(self):
        decision = self.policy.decide("read_file", "medium")

        self.assertEqual(decision.action, "ask")

    def test_vision_tool_requires_approval_when_marked_medium(self):
        decision = self.policy.decide("vision_analyze", "medium")

        self.assertEqual(decision.action, "ask")

    def test_high_risk_requires_approval(self):
        decision = self.policy.decide("powershell", "high")

        self.assertEqual(decision.action, "ask")

    def test_unknown_risk_is_denied(self):
        decision = self.policy.decide("unknown", "unexpected")

        self.assertEqual(decision.action, "deny")

    def test_allow_config_overrides_high_risk(self):
        policy = PermissionPolicy({"allow": ["powershell"]})

        decision = policy.decide("powershell", "high")

        self.assertEqual(decision.action, "allow")

    def test_ask_config_overrides_low_risk(self):
        policy = PermissionPolicy({"ask": ["calculator"]})

        decision = policy.decide("calculator", "low")

        self.assertEqual(decision.action, "ask")

    def test_deny_config_has_highest_priority(self):
        policy = PermissionPolicy({
            "allow": ["powershell"],
            "ask": ["powershell"],
            "deny": ["powershell"],
        })

        decision = policy.decide("powershell", "high")

        self.assertEqual(decision.action, "deny")

    def test_wildcard_can_match_mcp_tools(self):
        policy = PermissionPolicy({"ask": ["mcp__*"]})

        decision = policy.decide("mcp__amap__maps_search", "low")

        self.assertEqual(decision.action, "ask")

    def test_deny_wildcard_still_has_highest_priority(self):
        policy = PermissionPolicy({
            "allow": ["mcp__*"],
            "deny": ["mcp__danger__*"],
        })

        decision = policy.decide("mcp__danger__delete", "medium")

        self.assertEqual(decision.action, "deny")

    def test_session_allow_skips_future_approval(self):
        policy = PermissionPolicy()
        policy.allow_for_session("powershell")

        decision = policy.decide("powershell", "high")

        self.assertEqual(decision.action, "allow")

    def test_session_allow_cannot_override_deny_config(self):
        policy = PermissionPolicy({"deny": ["powershell"]})
        policy.allow_for_session("powershell")

        decision = policy.decide("powershell", "high")

        self.assertEqual(decision.action, "deny")


if __name__ == "__main__":
    unittest.main()
