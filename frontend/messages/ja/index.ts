import ask from "./ask.json";
import audit from "./audit.json";
import auth from "./auth.json";
import changeSets from "./changeSets.json";
import checklist from "./checklist.json";
import common from "./common.json";
import dashboard from "./dashboard.json";
import errors from "./errors.json";
import evalNs from "./eval.json";
import feedback from "./feedback.json";
import forms from "./forms.json";
import mockData from "./mockData.json";
import nav from "./nav.json";
import notifications from "./notifications.json";
import outputFeedback from "./outputFeedback.json";
import profile from "./profile.json";
import projects from "./projects.json";
import roles from "./roles.json";
import settings from "./settings.json";
import status from "./status.json";

/** The Japanese catalogue (machine-assisted first draft; see _meta.json). */
const messages = {
  ask,
  audit,
  auth,
  changeSets,
  checklist,
  common,
  dashboard,
  errors,
  eval: evalNs,
  feedback,
  forms,
  mockData,
  nav,
  notifications,
  outputFeedback,
  profile,
  projects,
  roles,
  settings,
  status,
};

export default messages;
