/**
 * App — receives gateway from entry, passes to useMainApp.
 */
import React, { useMemo, useEffect } from "react";
import { useMainApp } from "./hooks/useMainApp.js";
import { AppLayout } from "./components/AppLayout.js";
import { COMMANDS } from "./components/Composer.js";
import { SIERRA_THEME } from "./theme.js";
import type { Gateway } from "./gateway.js";

interface AppProps {
  gw: Gateway;
}

export const App: React.FC<AppProps> = ({ gw }) => {
  const app = useMainApp(gw);

  const hints = useMemo(
    () =>
      app.composer.state.input.startsWith("/") &&
      !app.pendingUserInput &&
      !app.composer.state.input.includes(" ")
        ? COMMANDS.filter((c) => c.cmd.startsWith(app.composer.state.input))
        : [],
    [app.composer.state.input, app.pendingUserInput]
  );

  const hintsKey = hints.map((h) => h.cmd).join(",");
  useEffect(() => { app.setHintIdx(0); }, [hintsKey]);

  function onSubmit(value: string) {
    if (app.pendingUserInput) {
      app.submitUserInput(value);
      return;
    }
    app.composer.refs.submitRef.current?.(value);
  }

  return (
    <AppLayout
      app={app}
      theme={SIERRA_THEME}
      hints={hints}
      hintIdx={app.hintIdx}
      onSubmit={onSubmit}
    />
  );
};
