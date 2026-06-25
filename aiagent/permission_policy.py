from dataclasses import dataclass
from fnmatch import fnmatchcase

@dataclass(frozen=True)
class PermissionDecision:
    action: str
    reason: str


class PermissionPolicy:
    def __init__(self, config=None):
        self.config = config or {}

        self.allow_tools = set(self.config.get("allow", []))
        self.deny_tools = set(self.config.get("deny", []))
        self.ask_tools = set(self.config.get("ask", []))
        self.session_allow_tools = set()

    def allow_for_session(self, tool_name: str) -> None:
        self.session_allow_tools.add(tool_name)

    def _matches(self, tool_name: str, patterns: set[str]) -> bool:
        return any(
            fnmatchcase(tool_name, pattern)
            for pattern in patterns
        )

    def decide(self, tool_name: str, risk_level: str) -> PermissionDecision:
        if self._matches(tool_name, self.deny_tools):
            return PermissionDecision(action="deny", reason="配置禁止该工具")
        if tool_name in self.session_allow_tools:
            return PermissionDecision(
                action="allow",
                reason="本次会话已授权该工具",
            )
      
        if self._matches(tool_name, self.allow_tools):
            return PermissionDecision(action="allow", reason="配置允许该工具")
        if self._matches(tool_name, self.ask_tools):
            return PermissionDecision(action="ask", reason="配置要求用户确认")
        

        if risk_level == "low":
            return PermissionDecision(action="allow", reason="低风险工具可以自动执行")
        
        if risk_level in ("medium", "high"):
            return PermissionDecision(action="ask", reason="中高风险工具需要用户确认")
        
        return PermissionDecision(action="deny", reason="未知风险等级，默认拒绝")
      