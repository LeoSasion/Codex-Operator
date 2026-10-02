"use strict";

// Isolated native-menu candidate. This file installs nothing, makes no network
// calls and grants no execution permission. Existing chats are not migrated.
const KEYS = ["model", "providerId", "provider", "catalogPath", "menuModel"];
const forbidden = new Set(["openai", "lmstudio", "ollama"]);
function reject(code) { throw new Error("operator_native_menu_" + code); }
function plain(value) {
  return value != null && typeof value === "object" &&
    !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype;
}
function registry(rows) {
  if (!Array.isArray(rows) || rows.length > 32) reject("registry_bound");
  const models = new Map();
  for (const row of rows) {
    if (!plain(row) || Object.keys(row).sort().join() !== KEYS.slice().sort().join() ||
        typeof row.model !== "string" || !row.model || row.model.length > 256 ||
        models.has(row.model) || /^gpt-|^beeper$/.test(row.model) ||
        !/^operator_native_[a-z0-9_]{1,64}$/.test(row.providerId) || forbidden.has(row.providerId) ||
        typeof row.catalogPath !== "string" || !row.catalogPath || row.catalogPath.length > 4096 ||
        !plain(row.provider) || !plain(row.menuModel)) reject("registration_invalid");
    const providerKeys = ["name", "base_url", "wire_api", "requires_openai_auth",
      "request_max_retries", "stream_max_retries", "supports_websockets"];
    if (Object.hasOwn(row.provider, "env_key")) providerKeys.push("env_key");
    if (Object.keys(row.provider).sort().join() !== providerKeys.sort().join() ||
        row.provider.wire_api !== "responses" || row.provider.requires_openai_auth !== false ||
        row.provider.request_max_retries !== 0 || row.provider.stream_max_retries !== 0 ||
        row.provider.supports_websockets !== false ||
        typeof row.provider.name !== "string" || !row.provider.name ||
        typeof row.provider.base_url !== "string" ||
        (Object.hasOwn(row.provider, "env_key") && !/^[A-Z][A-Z0-9_]{0,100}$/.test(row.provider.env_key)))
      reject("endpoint_invalid");
    let endpoint;
    try { endpoint = new URL(row.provider.base_url); } catch { reject("endpoint_invalid"); }
    if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash ||
        !(endpoint.protocol === "https:" || endpoint.protocol === "http:" &&
          ["127.0.0.1", "[::1]"].includes(endpoint.hostname))) reject("endpoint_invalid");
    if (row.menuModel.model !== row.model || row.menuModel.id !== row.model ||
        row.menuModel.isDefault !== false || row.menuModel.hidden !== false ||
        row.menuModel.supportsPersonality !== false ||
        typeof row.menuModel.displayName !== "string" || !row.menuModel.displayName ||
        !Array.isArray(row.menuModel.supportedReasoningEfforts)) reject("menu_identity_invalid");
    // Detach registrations from caller mutation; no credentials belong here.
    const copy = JSON.parse(JSON.stringify(row));
    Object.freeze(copy.provider);
    Object.freeze(copy.menuModel);
    Object.freeze(copy);
    models.set(row.model, copy);
  }
  return models;
}

function appendModelList(response, rows, hostKind) {
  if (hostKind !== "local") return response;
  const known = registry(rows);
  if (!known.size) return response;
  if (!plain(response) || !Array.isArray(response.data) || response.data.length > 1000)
    reject("model_list_invalid");
  if (response.nextCursor != null) return response; // Append once, at the final page.
  const ids = new Set();
  const models = new Set();
  for (const row of response.data) {
    if (!plain(row) || typeof row.id !== "string" || typeof row.model !== "string" ||
        ids.has(row.id) || models.has(row.model)) reject("model_list_identity_invalid");
    ids.add(row.id); models.add(row.model);
  }
  for (const row of known.values()) {
    if (ids.has(row.model) || models.has(row.model)) reject("model_collision");
  }
  return { ...response, data: [...response.data, ...[...known.values()].map(row => row.menuModel)] };
}

function prepareThreadStart(params, rows, hostKind) {
  if (hostKind !== "local") return params;
  if (!plain(params)) reject("thread_params_invalid");
  // A broken optional registration must never intercept an official startup.
  if (params.model == null || typeof params.model === "string" && params.model.startsWith("gpt-")) return params;
  const known = registry(rows);
  const row = known.get(params.model);
  if (!row) return params; // Official and auxiliary requests remain exactly opaque.
  if (params.modelProvider != null && params.modelProvider !== row.providerId)
    reject("provider_conflict");
  if (params.config != null && !plain(params.config)) reject("thread_config_invalid");
  const config = params.config ?? {};
  const key = "model_providers." + row.providerId;
  // Never deep-merge unknown inherited auth/header fields into an endpoint.
  if (Object.hasOwn(config, key) || Object.hasOwn(config, "model_providers") ||
      Object.hasOwn(config, "model_provider") || Object.hasOwn(config, "model_catalog_json"))
    reject("thread_config_conflict");
  return { ...params, modelProvider: row.providerId, config: {
    ...config, [key]: row.provider, model_catalog_json: row.catalogPath
  } };
}

function guardExistingThread(params, rows, currentProvider, hostKind) {
  if (hostKind !== "local") return params;
  if (!plain(params)) reject("thread_params_invalid");
  const model = params.collaborationMode?.settings?.model ?? params.model;
  if (model == null) return params;
  if (typeof model === "string" && model.startsWith("gpt-") &&
      (currentProvider == null || currentProvider === "openai")) return params;
  const row = registry(rows).get(model);
  if (!row && (currentProvider == null || currentProvider === "openai")) return params;
  if (row && currentProvider === row.providerId) return params;
  // Listing a model never authorizes sending a turn to a different endpoint.
  // The candidate has no supported same-chat migration and must say so.
  reject("same_chat_provider_switch_unverified");
}

module.exports = { registry, appendModelList, prepareThreadStart, guardExistingThread };
