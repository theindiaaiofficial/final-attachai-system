import { api, authenticate, logout } from "./api.js";
import { h, icon, button, heading, loader, toast, select } from "./ui.js";
import { clientsView, editClient } from "./clients.js";
import { conversationsView, knowledgeView, leadsView } from "./workspaces.js";
import { overviewView, analyticsView, providersView, systemView, activityView, docsView } from "./reports.js";

const pages = {
  overview:{label:"Overview",view:overviewView}, clients:{label:"Clients",view:clientsView},
  conversations:{label:"Conversations",view:conversationsView}, knowledge:{label:"Knowledge base",view:knowledgeView},
  leads:{label:"Leads",view:leadsView}, analytics:{label:"Analytics",view:analyticsView},
  providers:{label:"AI providers",view:providersView}, settings:{label:"System settings",view:systemView},
  activity:{label:"Activity log",view:activityView}, docs:{label:"Documentation",view:docsView},
};
let serial = 0;
const context = {
  clients:[],tenant:null,filters:{},
  navigate(page){ if(location.hash.slice(1)===page)render();else location.hash=page; },
  refresh(){ return render(); },
  setTenant(id){context.tenant=id;try{if(id)sessionStorage.setItem("orbit-selected-client",id);else sessionStorage.removeItem("orbit-selected-client");}catch{}context.filters.conversations={q:"",page:1};context.filters.knowledge={q:"",results:[]};context.filters.leads={q:"",status:"all",page:1};},
  tenantName(){return context.clients.find(row=>row.id===context.tenant)?.name||"Unknown client";},
  tenantSelector(){return select(context.tenant||"",context.clients.map(row=>({value:row.id,label:row.name})),id=>{context.setTenant(id);render();},"Select client");},
  createClient(){editClient(context);},
  async reloadClients(){
    let rows=[],page=1,total;
    do {const result=await api(`/admin/clients?page=${page++}&page_size=100`);rows.push(...result.items);total=result.total;}while(rows.length<total);
    context.clients=rows;
    const stored = context.tenant || (()=>{try{return sessionStorage.getItem("orbit-selected-client");}catch{return null;}})();
    if(rows.some(row=>row.id===stored)) context.tenant=stored;
    else context.setTenant(rows[0]?.id||null);
    try { if(context.tenant) sessionStorage.setItem("orbit-selected-client", context.tenant); } catch {}
  },
};

function route(){const key=location.hash.slice(1);return pages[key]?key:"overview";}

async function render(){
  const key=route(),page=pages[key],run=++serial;
  window.scrollTo(0, 0);
  document.title=`${page.label} · Orbit AI`;
  document.getElementById("breadcrumb-page").textContent=page.label;
  document.querySelectorAll("[data-page]").forEach(link=>{const active=link.dataset.page===key;link.classList.toggle("active",active);if(active)link.setAttribute("aria-current","page");else link.removeAttribute("aria-current");});
  document.body.classList.remove("mobile-open");
  const content=document.getElementById("content");content.replaceChildren(loader());
  try {const view=await page.view(context);if(run===serial)content.replaceChildren(view);}
  catch(error){if(run!==serial)return;content.replaceChildren(heading(page.label,""),h("section",{class:"error-panel",role:"alert"},h("h2",{},"We couldn’t load this page"),h("p",{},error.message),button("Try again",render,"primary","refresh")));}
}

const nav=document.getElementById("navigation");
for(const [key,page] of Object.entries(pages))nav.append(h("a",{href:`#${key}`,class:"nav-link","data-page":key,title:page.label},icon(key),h("span",{class:"nav-label"},page.label)));
document.getElementById("collapse-icon").append(icon("collapse"));
document.getElementById("mobile-menu").append(icon("menu"));
document.getElementById("theme-toggle").append(icon("theme"));
document.getElementById("search-icon").append(icon("search"));
document.getElementById("mobile-menu").addEventListener("click",()=>document.body.classList.toggle("mobile-open"));
document.getElementById("mobile-shade").addEventListener("click",()=>document.body.classList.remove("mobile-open"));
document.getElementById("collapse-nav").addEventListener("click",()=>{document.body.classList.toggle("collapsed");document.getElementById("collapse-nav").setAttribute("aria-label",document.body.classList.contains("collapsed")?"Expand navigation":"Collapse navigation");});
try {document.documentElement.dataset.theme=localStorage.getItem("orbit-theme")||"light";}catch{}
document.getElementById("theme-toggle").addEventListener("click",()=>{const theme=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=theme;try{localStorage.setItem("orbit-theme",theme);}catch{}});
document.getElementById("global-search").addEventListener("submit",event=>{event.preventDefault();context.filters.clients={q:event.currentTarget.elements.q.value,status:"all",page:1};context.navigate("clients");});
document.getElementById("logout").addEventListener("click",()=>logout().catch(error=>toast(error.message,true)));
window.addEventListener("hashchange",render);
window.addEventListener("auth-expired",()=>{document.querySelectorAll("dialog").forEach(node=>node.remove());location.replace("/admin/login");});

try {
  const session=await authenticate();
  if(session.expires_at){const expiry=new Date(session.expires_at);document.getElementById("session-label").textContent=`Expires ${expiry.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}`;setTimeout(()=>window.dispatchEvent(new Event("auth-expired")),Math.max(0,expiry-Date.now()));}
  await context.reloadClients(); await render();
}catch(error){
  document.getElementById("content").replaceChildren(h("section",{class:"error-panel"},h("h2",{},"Could not initialize the workspace"),h("p",{},error.message),button("Retry",()=>location.reload(),"primary")));
}
