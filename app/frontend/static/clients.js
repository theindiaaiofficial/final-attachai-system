import { api } from "./api.js";
import { h, icon, button, badge, heading, empty, table, field, dialog, confirmAction, toast, pagination, search, select, stamp, number } from "./ui.js";

function base(id) { return `/admin/clients/${encodeURIComponent(id)}`; }
function jsonObject(text) {
  const result = JSON.parse(text);
  if (!result || Array.isArray(result) || typeof result !== "object") throw new Error("Configuration must be a JSON object.");
  return result;
}

export function revealKey(key, client) {
  const input = h("input", {value:key,readonly:true,"aria-label":"One-time API key"});
  const embed = `<script src="${location.origin}/widget.js" data-base-url="${location.origin}" data-api-key="${key}"></script>`;
  dialog("Save your client API key",h("div",{},h("p",{},`A new key was issued for ${client.name}. It is only shown now. Closing this dialog removes it from the page.`),h("div",{class:"secret-panel"},input,button("Copy API key",async()=>{await navigator.clipboard.writeText(key);toast("API key copied.");},"","key")),h("h3",{class:"form-section"},"Widget installation"),h("p",{class:"text-muted"},"Add this script to an allowed website origin. This is a public widget credential, scoped by your configured origins."),h("pre",{class:"mono"},embed)));
}

export function editClient(context, original = null) {
  const config = original?.config || {};
  const grid = h("div",{class:"form-grid"},
    field("Client name","name",original?.name||"",{required:true,maxlength:120}),
    original ? field("Status","enabled",String(original.enabled),{select:[{value:"true",label:"Active"},{value:"false",label:"Suspended"}]}) : field("URL slug","slug","",{required:true,maxlength:63,attrs:{pattern:"[a-z0-9][a-z0-9-]{1,62}"},help:"2–63 lowercase letters, numbers, and hyphens."}),
    field("Allowed website origins","domains",(original?.domains||[]).join("\n"),{required:true,textarea:true,wide:true,rows:3,help:"One exact origin per line, including https:// and any non-default port. No paths or wildcards."}),
    field("Assistant name","assistantName",config.assistantName||"Assistant",{required:true,maxlength:80}),
    field("Business / brand name","businessName",config.businessName||original?.name||"",{maxlength:120,help:"Defaults to the client name when left blank."}),
    field("Assistant description","assistantDescription",config.assistantDescription||"",{maxlength:500,wide:true,help:"Used for identity questions; business facts still require tenant knowledge."}),
    field("Identity instructions","identityInstructions",config.identityInstructions||"",{maxlength:2000,textarea:true,wide:true,rows:3,help:"Optional tenant-specific identity guidance. Do not place credentials here."}),
    field("Notification email","notificationEmail",config.notificationEmail||config.teamEmail||"",{type:"email",maxlength:320}),
    field("Welcome message","welcomeMessage",config.welcomeMessage||"How can I help?",{maxlength:500,wide:true}),
    field("Assistant system prompt","prompt",original?.prompt||"Answer business questions using only the supplied knowledge. Say clearly when information is unavailable.",{required:true,maxlength:20000,textarea:true,wide:true,rows:6}),
    field("Full client configuration (JSON)","config",JSON.stringify(config,null,2),{textarea:true,wide:true,rows:5,help:"Existing configuration is preserved. Assistant name, email, and welcome message above take precedence."}),
  );
  dialog(original?"Edit client":"Create a client",grid,{submitText:original?"Save client":"Create client",submit:async data=>{
    let parsed;
    try { parsed=jsonObject(data.get("config")); } catch { throw new Error("Configuration must be a valid JSON object."); }
    const domains=data.get("domains").split(/[\n,]/).map(x=>x.trim()).filter(Boolean);
    if(!domains.length||domains.length>30)throw new Error("Provide between 1 and 30 website origins.");
    const body={name:data.get("name").trim(),domains,prompt:data.get("prompt"),config:{...parsed,assistantName:data.get("assistantName"),businessName:data.get("businessName"),assistantDescription:data.get("assistantDescription")||undefined,identityInstructions:data.get("identityInstructions")||undefined,welcomeMessage:data.get("welcomeMessage"),notificationEmail:data.get("notificationEmail")||undefined}};
    if(original)body.enabled=data.get("enabled")==="true";else body.slug=data.get("slug");
    const result=await api(original?base(original.id):"/admin/clients",{method:original?"PATCH":"POST",body});
    toast(original?"Client updated.":"Client created.");
    await context.reloadClients(); context.refresh();
    if(!original) revealKey(result.api_key,result);
  }});
}

export async function openClient(context, id) {
  const client = await api(base(id));
  const content = h("div",{},h("div",{class:"detail-grid"},[
    ["Status",client.enabled?"Active":"Suspended"],["API key",client.apiKey?.enabled?"Enabled":"Disabled"],["Conversations",number(client.stats?.conversations)],
  ].map(([k,v])=>h("div",{class:"detail-kv"},h("dt",{},k),h("dd",{},v)))),h("p",{class:"mono text-muted"},client.id),h("h3",{class:"form-section"},"Website origins"),h("p",{class:"mono"},client.domains.join("\n")),h("h3",{class:"form-section"},"Assistant prompt"),h("p",{class:"mono"},client.prompt));
  const box = dialog(client.name,content);
  const actions = h("div",{class:"toolbar-group form-section"});
  actions.append(
    button("Edit",()=>{box.close();editClient(context,client);},"primary","edit"),
    button(client.enabled?"Suspend":"Activate",()=>confirmAction(client.enabled?"Suspend this client?":"Activate this client?","This changes whether the tenant can use its public API key.",async()=>{await api(base(id),{method:"PATCH",body:{enabled:!client.enabled}});box.close();await context.reloadClients();context.refresh();toast("Client status updated.");}),""),
    button("Duplicate",()=>{box.close();duplicateClient(context,client);}),
    button("Rotate key",()=>confirmAction("Rotate API key?","Existing widget installations will stop working until updated with the new key.",async()=>{const result=await api(`${base(id)}/rotate-key`,{method:"POST"});box.close();revealKey(result.apiKey,client);context.refresh();},"Rotate key"),"","key"),
    button(client.apiKey?.enabled?"Disable key":"Enable key",()=>confirmAction("Change API key access?","This takes effect for public tenant requests immediately.",async()=>{await api(`${base(id)}/key/${client.apiKey?.enabled?"disable":"enable"}`,{method:"POST"});box.close();context.refresh();toast("Key access updated.");})),
    button("Prompt versions",()=>showVersions(context,client)),
    button("Reset prompt",()=>confirmAction("Reset assistant prompt?","The current prompt will be saved in version history.",async()=>{await api(`${base(id)}/prompts/reset`,{method:"POST"});box.close();context.refresh();toast("Prompt reset.");})),
    button("Delete client",()=>confirmAction("Permanently delete this client?","This removes the client, knowledge objects, linked conversations, leads, and API credentials. This cannot be undone.",async()=>{await api(base(id),{method:"DELETE",timeout:120000});box.close();await context.reloadClients();context.refresh();toast("Client deleted.");},"Delete client"),"danger","trash"),
  );
  actions.append(button("Widget",()=>{box.close();editWidget(context,client);},"",""));
  content.append(actions);
  content.append(h("h3",{class:"form-section"},"Manage client workspace"),h("div",{class:"toolbar-group"},["conversations","knowledge","leads","analytics"].map(page=>button(page[0].toUpperCase()+page.slice(1),()=>{box.close();context.setTenant(id);context.navigate(page);}))))
}

function duplicateClient(context, client) {
  dialog("Duplicate client",h("div",{class:"form-grid"},field("Client name","name",`${client.name} copy`,{required:true,maxlength:120}),field("New slug","slug","",{required:true,attrs:{pattern:"[a-z0-9][a-z0-9-]{1,62}"},maxlength:63})),{submitText:"Duplicate client",submit:async data=>{
    const result=await api(`${base(client.id)}/duplicate`,{method:"POST",body:{name:data.get("name"),slug:data.get("slug")}});
    await context.reloadClients();context.refresh();revealKey(result.api_key,result);
  }});
}


function editWidget(context, client) {
  const source = client.config || {};
  const current = source.widget || {};
  const theme = source.theme || {};
  const defaults = {
    primaryColor: theme.primaryColor || current.primaryColor || "#3854a6",
    panelColor: theme.panelColor || current.panelColor || "#ffffff",
    surfaceColor: theme.surfaceColor || current.surfaceColor || "#f8fafc",
    textColor: theme.textColor || current.textColor || "#172033",
    userBubbleColor: theme.userBubbleColor || current.userBubbleColor || "#edf2ff",
    position: current.position || "right",
    launcherText: current.launcherText || "Chat",
    width: current.width || 420,
    height: current.height || 690,
    radius: current.radius || 22,
    launcherSize: current.launcherSize || "normal",
    logoUrl: current.logoUrl || "",
    headerSubtitle: current.headerSubtitle || "",
  };
  const grid = h("div", {class:"form-grid"},
    field("Brand / accent color", "primaryColor", defaults.primaryColor, {type:"color"}),
    field("Chat panel color", "panelColor", defaults.panelColor, {type:"color"}),
    field("Message area background", "surfaceColor", defaults.surfaceColor, {type:"color"}),
    field("Text color", "textColor", defaults.textColor, {type:"color"}),
    field("Visitor message bubble", "userBubbleColor", defaults.userBubbleColor, {type:"color"}),
    field("Widget position", "position", defaults.position, {select:[{value:"right",label:"Bottom right"},{value:"left",label:"Bottom left"}]}),
    field("Launcher button text", "launcherText", defaults.launcherText, {maxlength:24}),
    field("Launcher button size", "launcherSize", defaults.launcherSize, {select:[{value:"compact",label:"Compact"},{value:"normal",label:"Normal"},{value:"large",label:"Large"}]}),
    field("Chat window width (px)", "width", String(defaults.width), {type:"number",attrs:{min:"320",max:"560",step:"10"}}),
    field("Chat window height (px)", "height", String(defaults.height), {type:"number",attrs:{min:"420",max:"820",step:"10"}}),
    field("Corner roundness (px)", "radius", String(defaults.radius), {type:"number",attrs:{min:"8",max:"32",step:"1"}}),
    field("Logo image URL (optional)", "logoUrl", defaults.logoUrl, {type:"url",maxlength:1000,wide:true,help:"Use a publicly accessible HTTPS image URL. Leave blank for the default Orbit icon."}),
    field("Header subtitle (optional)", "headerSubtitle", defaults.headerSubtitle, {maxlength:80,wide:true}),
  );
  const preview = h("div", {class:"widget-custom-preview"},
    h("div", {class:"widget-preview-head"}, h("strong", {}, client.config?.assistantName || "Assistant"), h("span", {}, "Online")),
    h("div", {class:"widget-preview-body"},
      h("div", {class:"widget-preview-bubble"}, "Hello! How can I help you today?"),
      h("div", {class:"widget-preview-user"}, "I have a question")),
    h("div", {class:"widget-preview-input"}, "Type your message…"));
  const wrapper = h("div", {},
    h("p", {class:"text-muted"}, "These design settings apply only to this client. The existing website embed code and API key stay the same."),
    grid,
    h("h3", {class:"form-section"}, "Live preview"),
    preview);
  dialog("Customize website widget", wrapper, {submitText:"Save widget design", submit:async data => {
    const colors = {};
    for (const key of ["primaryColor","panelColor","surfaceColor","textColor","userBubbleColor"]) {
      const value = String(data.get(key) || "").trim();
      if (!/^#[0-9a-fA-F]{6}$/.test(value)) throw new Error("Please choose valid colors for all color fields.");
      colors[key] = value;
    }
    const position = data.get("position");
    const launcherSize = data.get("launcherSize");
    if (!["left","right"].includes(position)) throw new Error("Choose a valid widget position.");
    if (!["compact","normal","large"].includes(launcherSize)) throw new Error("Choose a valid launcher size.");
    const width = Number(data.get("width"));
    const height = Number(data.get("height"));
    const radius = Number(data.get("radius"));
    if (!Number.isInteger(width) || width < 320 || width > 560) throw new Error("Chat window width must be between 320 and 560 px.");
    if (!Number.isInteger(height) || height < 420 || height > 820) throw new Error("Chat window height must be between 420 and 820 px.");
    if (!Number.isInteger(radius) || radius < 8 || radius > 32) throw new Error("Corner roundness must be between 8 and 32 px.");
    const logoUrl = String(data.get("logoUrl") || "").trim();
    if (logoUrl) {
      let parsed;
      try { parsed = new URL(logoUrl); } catch { throw new Error("Enter a valid logo URL."); }
      if (parsed.protocol !== "https:") throw new Error("Logo URL must use HTTPS.");
    }
    const widget = {
      ...current,
      ...colors,
      position,
      launcherSize,
      launcherText: String(data.get("launcherText") || "Chat").trim().slice(0,24) || "Chat",
      width, height, radius, logoUrl,
      headerSubtitle: String(data.get("headerSubtitle") || "").trim().slice(0,80),
    };
    const config = {...source, widget, theme:{...theme, ...colors}};
    await api(base(client.id), {method:"PATCH", body:{config}});
    toast("Widget design saved.");
    context.refresh();
  }});

  const controls = wrapper.querySelectorAll("input,select");
  const updatePreview = () => {
    const values = Object.fromEntries([...controls].map(el => [el.name, el.value]));
    preview.style.setProperty("--preview-primary", values.primaryColor || defaults.primaryColor);
    preview.style.setProperty("--preview-panel", values.panelColor || defaults.panelColor);
    preview.style.setProperty("--preview-surface", values.surfaceColor || defaults.surfaceColor);
    preview.style.setProperty("--preview-text", values.textColor || defaults.textColor);
    preview.style.setProperty("--preview-user", values.userBubbleColor || defaults.userBubbleColor);
    preview.style.setProperty("--preview-radius", `${Math.min(32, Math.max(8, Number(values.radius) || 22))}px`);
    preview.querySelector(".widget-preview-head strong").textContent = client.config?.assistantName || "Assistant";
  };
  controls.forEach(el => el.addEventListener("input", updatePreview));
  updatePreview();
}

async function showVersions(context, client) {
  const rows=await api(`${base(client.id)}/prompts/history`);
  dialog("Prompt version history",rows.length?h("div",{},rows.map(row=>h("div",{class:"message"},h("div",{class:"message-head"},stamp(row.created_at)),h("p",{class:"mono"},row.prompt),button("Restore this version",()=>confirmAction("Restore this prompt?","The current prompt will be saved before restoring this version.",async()=>{await api(`${base(client.id)}/prompts/${row.id}/restore`,{method:"POST"});toast("Prompt restored.");context.refresh();}))))):empty("No previous versions","Edit the assistant prompt to create version history.","clock"));
}

export async function clientsView(context) {
  const f = context.filters.clients ||= {q:"",status:"all",page:1};
  const result = await api(`/admin/clients?${new URLSearchParams({q:f.q,status:f.status,page:f.page,page_size:15})}`);
  const update = values => {Object.assign(f,{page:1},values);context.refresh();};
  const panel = h("section",{class:"card"},h("div",{class:"toolbar"},h("div",{class:"toolbar-group"},search(f.q,q=>update({q}),"Search name or slug…"),select(f.status,[{value:"all",label:"All statuses"},{value:"active",label:"Active"},{value:"suspended",label:"Suspended"}],status=>update({status}),"Client status")),badge(`${result.total} clients`)));
  panel.append(result.items.length?table(["Client","Status","Allowed origins","API key","Created",""],result.items.map(row=>[
    h("div",{class:"cell-primary"},h("span",{class:"client-avatar"},row.name.slice(0,2).toUpperCase()),h("div",{},h("button",{class:"row-link",onclick:()=>openClient(context,row.id).catch(e=>toast(e.message,true))},row.name),h("small",{},row.slug))),
    badge(row.enabled?"Active":"Suspended",row.enabled?"success":"warning"),h("span",{class:"mono truncate",title:row.domains.join(", ")},row.domains[0]||"None",row.domains.length>1?` +${row.domains.length-1}`:""),badge(row.apiKey?.enabled?"Enabled":"Disabled",row.apiKey?.enabled?"success":""),h("span",{class:"text-muted"},stamp(row.created_at)),h("div",{class:"actions"},button("Manage",()=>openClient(context,row.id),"small","arrow")),
  ])):empty(f.q?"No matching clients":"Your first client starts here",f.q?"Try a different name or change the status filter.":"Create a client to configure its assistant, website origins, and knowledge.","clients",button("Create client",()=>editClient(context),"primary","plus")));
  panel.append(pagination(f.page,result.total,15,page=>update({page})));
  return h("div",{},heading("Clients","Manage your customer workspaces, assistants, and access.",button("Create client",()=>editClient(context),"primary","plus")),panel);
}
