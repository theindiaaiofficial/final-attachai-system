import { api } from "./api.js";
import { h, icon, button, badge, tone, heading, card, empty, table, field, dialog, toast, pagination, search, select, stamp, stat, chart, notice } from "./ui.js";

function activityRows(rows, context) {
  if(!rows.length)return empty("No activity recorded","Administrative actions will be recorded here as you work.","activity");
  return h("div",{class:"activity-list"},rows.map(row=>h("div",{class:"activity-item"},h("span",{class:"activity-mark"},icon("activity")),h("div",{},h("p",{},row.action.replaceAll("."," · ")),h("small",{},context.clients.find(x=>x.id===row.client_id)?.name||(row.client_id?"Deleted client":"Platform"))),h("time",{},stamp(row.created_at)))));
}

function chartCard(series, title = "Conversation activity") {
  return card(title,"Conversations and leads by UTC day · last 30 days",h("div",{},h("div",{class:"card-body"},h("div",{class:"chart-legend"},h("span",{},h("i",{class:"legend-dot"}),"Conversations"),h("span",{},h("i",{class:"legend-dot green"}),"Leads")),chart(series)),h("div",{class:"chart-foot"},h("span",{},"Based on persisted source records"),h("span",{},"UTC"))));
}

export async function overviewView(context){
  const [data,status]=await Promise.all([api("/admin/overview"),api("/admin/status")]);
  const stats=h("div",{class:"stats-grid"},stat("Total clients",data.clients,"All customer workspaces","clients"),stat("Active clients",data.active_clients,"Enabled and ready for access","shield"),stat("Conversations",data.conversations,"All-time recorded sessions","conversations"),stat("Total leads",data.leads,"All-time captured contacts","leads"));
  const statusBody=h("div",{class:"card-body"},[
    ["Database",status.database.status,status.database.status==="ok"?"success":"error","database"],
    ["Storage",status.storage.status,["ok","configured"].includes(status.storage.status)?"success":"warning","knowledge"],
    ["RAG pipeline","RAG-2.0","purple","providers"],
    ["Configuration",status.issues.length?"Needs attention":"Configured",status.issues.length?"warning":"success","settings"],
  ].map(([name,value,color,symbol])=>h("div",{class:"status-row"},h("div",{class:"status-name"},icon(symbol),name),badge(value,color))),h("div",{class:"section-label"},"KNOWLEDGE PROCESSING"),[
    ["Ready documents",data.knowledge_status.ready||0],["Processing",data.knowledge_status.processing||0],["Failed",data.knowledge_status.error||0]
  ].map(([name,value])=>h("div",{class:"status-row"},h("span",{class:"text-muted"},name),h("strong",{},value))),h("p",{class:"stat-note section-label"},"Provider completion tests are explicit."));
  const providers=h("div",{class:"card-body"},["router","answer","embedding"].map(role=>h("div",{class:"status-row"},h("div",{},h("strong",{},role[0].toUpperCase()+role.slice(1)),h("p",{class:"stat-note"},data.providers[role]?.model||"No model configured")),badge(data.providers[role]?.provider||"Not configured",data.providers[role]?.provider?"purple":"warning"))),button("Manage providers",()=>context.navigate("providers"),"wide subtle","arrow"));
  return h("div",{},heading("Overview","A clear view of your AI platform. Everything in one place.",button("Refresh",()=>context.refresh(),"","refresh"),button("Create client",()=>context.createClient(),"primary","plus")),
    stats,h("div",{class:"overview-grid"},h("div",{},chartCard(data.series),card("Recent activity","The latest changes across your workspace",activityRows(data.recentAudits,context),button("View all",()=>context.navigate("activity"),"subtle small","arrow"))),h("div",{},card("System status","Live local dependency checks",statusBody,badge(status.database.status==="ok"?"Operational":"Attention",status.database.status==="ok"?"success":"warning")),card("AI infrastructure","Active role configuration",providers))),
    status.issues.length?notice("Setup needs attention: "+status.issues.join(" · "),true):null);
}

export async function analyticsView(context){
  const f=context.filters.analytics||={days:"30",scope:"all"};
  const query=new URLSearchParams({days:f.days});
  if(f.scope==="client"&&context.tenant)query.set("client_id",context.tenant);
  const data=await api(`/admin/analytics?${query}`);
  const update=changes=>{Object.assign(f,changes);context.refresh();};
  const controls=h("div",{class:"toolbar-group"},select(f.scope,[{value:"all",label:"All clients"},{value:"client",label:"Selected client"}],scope=>update({scope}),"Analytics scope"),f.scope==="client"?context.tenantSelector():null,select(f.days,[{value:"30",label:"Last 30 days"},{value:"90",label:"Last 90 days"},{value:"365",label:"Last 12 months"}],days=>update({days}),"Activity period"));
  const seriesBody=h("div",{class:"card-body"},h("div",{class:"chart-legend"},h("span",{},h("i",{class:"legend-dot"}),"Conversations"),h("span",{},h("i",{class:"legend-dot green"}),"Leads")),chart(data.series));
  const routes=Object.entries(data.routes);
  return h("div",{},heading("Analytics","Actual activity, route distribution, and performance.",controls),
    h("div",{class:"stats-grid"},stat("Conversations",data.conversations,"All-time in selected scope","conversations"),stat("Leads generated",data.leads,"All-time in selected scope","leads"),stat("Completed requests",data.requests,"Persisted pipeline usage records","providers"),stat("Avg. response (ms)",data.average_latency_ms,"All-time pipeline latency","clock")),
    card("Activity over time",`Daily records for the last ${f.days} days · UTC`,seriesBody),
    h("div",{class:"overview-grid"},card("Client usage","All-time counts from persisted records",data.client_usage.length?table(["Client","Conversations","Leads","Requests"],data.client_usage.map(row=>[row.name,row.conversations,row.leads,row.requests])):empty("No client activity","Create a client to begin tracking usage.","analytics")),card("Conversation routes","All-time completed pipeline decisions",routes.length?table(["Route","Requests"],routes.map(([key,value])=>[h("span",{class:"cell-wrap mono"},key),value])):empty("No route data yet","Completed requests will appear here.","providers"))),
    notice("Knowledge contains "+data.documents+" source documents. Provider token/cost accounting and source-hit usage are unavailable; the pipeline does not persist those metrics."));
}

export async function providersView(context){
  const data=await api("/admin/settings/provider");
  const running=data.running;
  const cards=["router","answer","embedding"].map(role=>{
    const info=running[role];
    const checks=role==="embedding"?badge("Embedding role","purple"):badge(info.completion_status.status,tone(info.completion_status.status));
    const content=h("div",{class:"card-body"},h("div",{class:"provider-logo"},icon("providers")),badge(role==="router"?"LLM 1 · Router":role==="answer"?"LLM 2 · Answer":"Embeddings","purple"),h("h3",{class:"provider-name"},info.provider||"Not configured"),h("dl",{class:"provider-details"},h("div",{},h("dt",{},"Model"),h("dd",{class:"mono"},info.model||"Not set")),h("div",{},h("dt",{},role==="embedding"?"Vector dimension":"API base"),h("dd",{class:"mono"},role==="embedding"?String(info.dimension):info.api_base||"Provider default")),h("div",{},h("dt",{},role==="embedding"?"Embedding fingerprint":"Credentials"),h("dd",{class:"mono"},role==="embedding"?info.fingerprint:info.credentials_present?"Configured on server · hidden":"Not configured"))),checks);
    if(role!=="embedding")content.append(button("Test completion",async()=>{const result=await api("/admin/settings/provider/test",{method:"POST",body:{role},timeout:20000});toast(result.connected?"Provider completion succeeded.":"Completion failed. Check server configuration.",!result.connected);context.refresh();},"wide form-section","refresh"));
    else content.append(h("p",{class:"stat-note form-section"},"Embedding changes require tenant reindexing and a compatible SQL schema."));
    return h("section",{class:"card provider-card"},h("div",{class:"card-head"},h("h2",{},role[0].toUpperCase()+role.slice(1))),content);
  });
  return h("div",{},heading("AI providers","Independent model roles. One provider-neutral architecture.",button("Configure roles",()=>configureProviders(context,data),"primary","settings")),
    notice("API keys are server-only environment variables. Connection tests send a short request to the active configured model; a configured key alone does not prove availability."),data.staged?notice("Saved role settings apply on the next process restart. Update the corresponding environment credentials before restarting. The cards below show the currently running configuration.",true):null,h("div",{class:"provider-grid"},cards),
    data.staged?card("Saved configuration","Pending restart · no credentials persisted",h("div",{class:"card-body mono"},JSON.stringify(data.staged,null,2))):null);
}

function configureProviders(context,data){
  const values=data.staged||data.running;
  const body=h("div",{},notice("Only non-secret role settings are saved. Set ROUTER_API_KEY / ANSWER_API_KEY in Render or .env, then restart. Public HTTPS API bases only."));
  for(const role of ["router","answer"]){const info=values[role];body.append(h("h3",{class:"form-section"},role==="router"?"Router role":"Answer role"),h("div",{class:"form-grid"},field("LiteLLM provider",`${role}_provider`,info.provider||"",{required:true,attrs:{pattern:"[a-zA-Z0-9_-]+"},maxlength:80,help:"For example: groq, nvidia_nim, openrouter, openai."}),field("Model identifier",`${role}_model`,info.model||"",{required:true,maxlength:200}),field("API base URL",`${role}_api_base`,info.api_base||"",{type:"url",wide:true,maxlength:500,help:"Leave blank for the provider default. HTTPS only; private endpoints are rejected."})));}
  dialog("Configure provider roles",body,{submitText:"Save for restart",submit:async form=>{
    const payload={};for(const role of ["router","answer"])payload[role]={provider:form.get(`${role}_provider`),model:form.get(`${role}_model`),api_base:form.get(`${role}_api_base`)||null};
    await api("/admin/settings/provider",{method:"PUT",body:payload});toast("Provider settings saved. Restart required.");context.refresh();
  }});
}

export async function systemView(){
  const [data,status]=await Promise.all([api("/admin/settings/system"),api("/admin/status")]);
  const groups=[
    ["Application",["app_environment","log_level","session_hours","database_provider","storage_provider","vector_provider"]],
    ["Retrieval & memory",["chunk_size","chunk_overlap","top_k","min_similarity","context_limit","history_limit"]],
    ["Embedding contract",["embedding_model","embedding_dimensions"]],
  ];
  const label=key=>({app_environment:"Environment",log_level:"Logging level",session_hours:"Session lifetime (hours)",database_provider:"Database",storage_provider:"Storage",vector_provider:"Vector store",chunk_size:"Chunk size (characters)",chunk_overlap:"Chunk overlap",top_k:"Top-K",min_similarity:"Minimum similarity",context_limit:"Context character limit",history_limit:"History message limit",embedding_model:"Model",embedding_dimensions:"Dimensions"})[key];
  const cards = groups.map(([title, keys]) => {
    const rows = keys.map(key => h("div", {class:"settings-row"}, h("span",{},label(key)), h("strong",{},String(data[key]))));
    return card(title, "Active configuration", h("div",{class:"card-body"},rows));
  });
  const readiness = h("div", {class:"card-body"},
    badge(status.readiness,status.issues.length?"warning":"success"),
    status.issues.length ? h("ul",{},status.issues.map(issue=>h("li",{class:"text-muted"},issue))) : h("p",{class:"stat-note form-section"},"Required configuration appears present. Use provider tests to verify completions."),
    h("p",{class:"stat-note form-section"},status.delivery),
    h("h3",{class:"form-section"},"Application CORS origins"),
    h("p",{class:"mono"},data.cors_origins.join("\n")||"No application-level origins configured; tenant origins are managed independently.")
  );
  return h("div",{},heading("System settings","Inspect the active deployment configuration. Credentials stay private."),
    notice("System settings are read-only. Update environment variables in your deployment and restart to apply changes."),
    h("div",{class:"settings-grid"},cards),
    card("Readiness & operations","Configuration state is distinct from successful external provider calls.",readiness));
}

export async function activityView(context){
  const f=context.filters.activity||={q:"",page:1,scope:"all"};
  const params=new URLSearchParams({q:f.q,page:f.page,page_size:20});if(f.scope==="client"&&context.tenant)params.set("client_id",context.tenant);
  const result=await api(`/admin/activity?${params}`);
  const update=changes=>{Object.assign(f,{page:1},changes);context.refresh();};
  const panel=h("section",{class:"card"},h("div",{class:"toolbar"},h("div",{class:"toolbar-group"},search(f.q,q=>update({q}),"Search activity action…"),select(f.scope,[{value:"all",label:"All activity"},{value:"client",label:"Selected client"}],scope=>update({scope}),"Activity scope"),f.scope==="client"?context.tenantSelector():null),badge(`${result.total} events`)));
  panel.append(result.items.length?table(["Action","Client scope","Timestamp"],result.items.map(row=>[badge(row.action),context.clients.find(x=>x.id===row.client_id)?.name||(row.client_id?"Deleted client":"Platform"),stamp(row.created_at)])):empty("No matching activity","Sensitive administrative actions are recorded automatically.","activity"));
  panel.append(pagination(f.page,result.total,20,page=>update({page})));
  return h("div",{},heading("Activity log","An audit trail of changes to your platform."),panel);
}

export async function docsView(){
  return h("div",{},heading("Documentation","Practical guidance for running your Orbit workspace."),h("section",{class:"card docs-content"},h("div",{class:"card-body"},
    h("h2",{},"1. Create a client"),h("p",{},"Open Clients → Create client. Set a name, unique lowercase slug, and exact website origins. Set the assistant’s prompt and presentation configuration. Save the one-time API key in your approved secret store; Orbit stores only a digest."),
    h("h2",{},"2. Add tenant knowledge"),h("p",{},"Select the client in Knowledge base, upload supported documents, and wait for the per-file processing result. Business answers use only that client’s indexed evidence. Image-only PDFs need external OCR. Rebuild reads stored originals and reports actual completion or errors."),
    h("h2",{},"3. Install the widget"),h("p",{},"Use the embed snippet shown with the one-time key, or rotate the key to generate a fresh installation credential. The website Origin must exactly match the configured allowlist."),
    h("pre",{},h("code",{},`<script src="${location.origin}/widget.js"\n  data-base-url="${location.origin}"\n  data-api-key="YOUR_PUBLIC_TENANT_KEY"></script>`)),
    h("h2",{},"4. Manage conversations and leads"),h("p",{},"Choose a client before browsing sessions, citations, or leads. Lead status, assignee, notes, and contact information can be edited. CSV export neutralizes spreadsheet formulas. Session deletion requires confirmation."),
    h("h2",{},"5. Configure AI providers"),h("p",{},"Router and answer roles are independent. Save non-secret provider/model/base settings, set matching API keys in Render Environment Variables or your local .env, then restart. Tests use the running model. Embedding model/dimension changes require a tenant reindex and compatible vector migration."),
    h("h2",{},"Security and deployment"),h("p",{},"Browser sessions are opaque HttpOnly cookies with SameSite=Strict, fixed expiry, CSRF protection, and server-side logout. ADMIN_SESSION_HOURS controls expiry. Production cookies require HTTPS. Changing ADMIN_API_KEY invalidates existing sessions. Apply migrations 0001, 0002, then 0003_admin_dashboard.sql before starting Supabase deployments."),
    h("pre",{},"pip install -r requirements.txt\nuvicorn app.main:app --host 0.0.0.0 --port $PORT"),
    h("h2",{},"Data and supported metrics"),h("p",{},"Analytics counts come from persisted records. No token costs, top-page data, or per-source usage is fabricated. Outbox entries remain pending without a delivery adapter. Documents/history are processed by the configured external embedding and LLM providers."),
    h("p",{},h("a",{href:"/docs",target:"_blank",rel:"noopener"},"Open the generated API reference ↗"))
  )));
}
