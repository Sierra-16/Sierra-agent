/**
 * Sierra TUI entry — standard ink v6.
 */
import React from "react";
import { render } from "ink";
import { Gateway } from "./gateway.js";
import { App } from "./app.js";
import { LAUNCH_CWD, VENV_PYTHON, SIERRA_DIR } from "./config.js";

const gw = new Gateway();
gw.start(VENV_PYTHON, SIERRA_DIR, LAUNCH_CWD);

render(React.createElement(App, { gw }), { exitOnCtrlC: false, patchConsole: false });
