import { UserManager, WebStorageStateStore } from "oidc-client-ts";

export const OIDC_REQUIRED = String(import.meta.env.VITE_OIDC_REQUIRED || "false").toLowerCase() === "true";

const KEYCLOAK_URL = (import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:8081").replace(/\/$/, "");
const REALM = import.meta.env.VITE_KEYCLOAK_REALM || "neurosoc";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID || "neurosoc-dashboard";

let manager = null;

export function getUserManager() {
  if (manager) return manager;
  manager = new UserManager({
    authority: `${KEYCLOAK_URL}/realms/${REALM}`,
    client_id: CLIENT_ID,
    redirect_uri: `${window.location.origin}/callback`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: "code",
    scope: "openid profile",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
  });
  return manager;
}

export function rolesFromUser(user) {
  if (!user?.profile) return [];
  const claims = user.profile;
  const realmRoles = claims.realm_access?.roles || [];
  const clientRoles = claims.resource_access?.[CLIENT_ID]?.roles || [];
  return [...new Set([...realmRoles, ...clientRoles])];
}

export async function signIn() {
  await getUserManager().signinRedirect();
}

export async function signOut() {
  await getUserManager().signoutRedirect();
}

export async function loadCurrentUser() {
  try {
    return await getUserManager().getUser();
  } catch {
    return null;
  }
}

export async function getAccessToken() {
  const user = await loadCurrentUser();
  return user && !user.expired ? user.access_token : null;
}
