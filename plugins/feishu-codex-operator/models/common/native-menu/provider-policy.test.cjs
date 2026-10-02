"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const policy = require("./provider-policy.cjs");
function row() { return {
  model: "fixture/exact-model", providerId: "operator_native_local_fixture",
  catalogPath: "C:/private/fixture.catalog.json",
  provider: {name: "Fixture", base_url: "http://127.0.0.1:19432/v1", wire_api: "responses",
    requires_openai_auth: false, request_max_retries: 0, stream_max_retries: 0, supports_websockets: false},
  menuModel: {id: "fixture/exact-model", model: "fixture/exact-model", displayName: "Local fixture [unverified]",
    description: "Fixture", hidden: false, isDefault: false, supportsPersonality: false,
    defaultReasoningEffort: "none", supportedReasoningEfforts: [{reasoningEffort: "none", description: "none"}]}
}; }
test("official and auxiliary startup preserve exact object identity and all fields", () => {
  for (const model of ["gpt-6.1-sol", "gpt-5.6-luna", null]) {
    const params={model,modelProvider:null,config:{permissions:"original"},developerInstructions:"original",opaque:{value:1}};
    assert.equal(policy.prepareThreadStart(params,[row()],"local"),params);
    assert.equal(policy.prepareThreadStart(params,null,"local"),params);
  }
});
test("external startup binds exact provider without modifying defaults, caller or permissions", () => {
  const params={model:row().model,modelProvider:null,approvalPolicy:"on-request",config:{features:{plugins:true}}};
  const before=JSON.stringify(params), result=policy.prepareThreadStart(params,[row()],"local");
  assert.equal(result.modelProvider,row().providerId);
  assert.equal(result.config.model_catalog_json,row().catalogPath);
  assert.deepEqual(result.config["model_providers."+row().providerId],row().provider);
  assert.equal(result.approvalPolicy,params.approvalPolicy);
  assert.equal(result.config.features,params.config.features);
  assert.equal(JSON.stringify(params),before);
  assert.equal(Object.hasOwn(result.config,"model_provider"),false);
});
test("native model rows and response metadata remain intact when custom rows append", () => {
  const official={id:"native",model:"gpt-6.1-sol",unknown:{original:true}}, response={data:[official],nextCursor:null,extra:"original"};
  const result=policy.appendModelList(response,[row()],"local");
  assert.equal(result.data[0],official); assert.equal(result.extra,"original");
  assert.equal(result.data.length,2); assert.equal(response.data.length,1);
  assert.equal(result.data[1].model,row().model); assert.equal(result.data[1].isDefault,false);
});
test("other hosts and non-final pages remain untouched", () => {
  const response={data:[],nextCursor:"opaque"}, params={model:row().model};
  assert.equal(policy.appendModelList(response,[row()],"local"),response);
  assert.equal(policy.appendModelList(response,[row()],"remote"),response);
  assert.equal(policy.prepareThreadStart(params,[row()],"remote"),params);
});
test("unknown auth, provider collisions and explicit routing conflicts are rejected", () => {
  assert.throws(()=>policy.registry([{...row(),provider:{...row().provider,http_headers:{Authorization:"fixture"}}}]),/endpoint_invalid/);
  assert.throws(()=>policy.registry([{...row(),model:"gpt-6.1-sol"}]),/registration_invalid/);
  assert.throws(()=>policy.registry([row(),row()]),/registration_invalid/);
  assert.throws(()=>policy.appendModelList({data:[row().menuModel],nextCursor:null},[row()],"local"),/model_collision/);
  assert.throws(()=>policy.prepareThreadStart({model:row().model,modelProvider:"openai"},[row()],"local"),/provider_conflict/);
  for(const config of [{model_provider:"openai"},{model_catalog_json:"later"},{model_providers:{unrelated:true}}, {["model_providers."+row().providerId]:{later:true}}])
    assert.throws(()=>policy.prepareThreadStart({model:row().model,config},[row()],"local"),/thread_config_conflict/);
});
test("endpoint checks reject public plaintext, credentials and private query strings", () => {
  for(const base_url of ["http://public.example/v1","https://user:pass@example.test/v1","http://127.0.0.1:19432/v1?token=fixture"])
    assert.throws(()=>policy.registry([{...row(),provider:{...row().provider,base_url}}]),/endpoint_invalid/);
});
test("a model shown in the menu cannot redirect an existing chat", () => {
  const local={model:row().model}, native={model:"gpt-6.1-sol"};
  assert.equal(policy.guardExistingThread(local,[row()],row().providerId,"local"),local);
  assert.equal(policy.guardExistingThread(native,[row()],"openai","local"),native);
  assert.equal(policy.guardExistingThread(native,null,"openai","local"),native);
  for (const provider of ["openai",null,"operator_native_other"])
    assert.throws(()=>policy.guardExistingThread(local,[row()],provider,"local"),/same_chat_provider_switch_unverified/);
  assert.throws(()=>policy.guardExistingThread(native,[row()],row().providerId,"local"),/same_chat_provider_switch_unverified/);
  assert.throws(()=>policy.guardExistingThread({model:"gpt-6.1-sol",collaborationMode:{settings:{model:row().model}}},[row()],"openai","local"),/same_chat_provider_switch_unverified/);
});
