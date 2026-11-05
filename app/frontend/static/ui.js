// All API/model/document content is inserted with text nodes, never HTML parsing.
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "text") node.textContent = value;
    else if (key === "value") node.value = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const paths = {
  overview: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  clients: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  conversations: "M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5",
  knowledge: "M4 3h5a4 4 0 0 1 4 4v15a3 3 0 0 0-3-3H4zM20 3h-4a3 3 0 0 0-3 3v16a3 3 0 0 1 3-3h4z",
  leads: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M18 5h4M20 3v4",
  analytics: "M3 3v18h18M7 16l4-5 4 3 6-8",
  providers: "M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3M6 6h12v12H6zM10 10h4v4h-4z",
  settings: "M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  activity: "M4 4h16v16H4zM8 8h8M8 12h8M8 16h5",
  docs: "M14 2H5v20h14V7zM14 2v6h6M8 12h8M8 16h6",
  search: "M21 21l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0",
  plus: "M12 5v14M5 12h14", arrow: "M5 12h14M13 6l6 6-6 6",
  refresh: "M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1",
  close: "M6 6l12 12M6 18 18 6", menu: "M3 6h18M3 12h18M3 18h18",
  theme: "M21 13a9 9 0 0 1-10-10 9 9 0 1 0 10 10",
  collapse: "M9 4H3v16h6M16 8l-4 4 4 4M12 12h9",
  check: "M5 12l4 4L19 6", upload: "M12 16V3M7 8l5-5 5 5M4 15v6h16v-6",
  download: "M12 3v13M7 11l5 5 5-5M4 17v4h16v-4",
  trash: "M3 6h18M5 6l1 15h12l1-15M9 6V3h6v3M10 10v7M14 10v7",
  edit: "M15 5l4 4M4 16l12-12 4 4L8 20H4z",
  clock: "M12 7v5l4 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  database: "M3 5c0-4 18-4 18 0s-18 4-18 0M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0",
  shield: "M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7zM8 12l3 3 5-6",
  info: "M12 11v6M12 7v1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  key: "M15 15l-6 6H5v-4l6-6M21 7a6 6 0 1 1-12 0 6 6 0 0 1 12 0",
};
export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-linecap":"round","stroke-linejoin":"round",class:"icon","aria-hidden":"true"})) svg.setAttribute(key, value);
  const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", paths[name] || paths.info); svg.append(path); return svg;
}

export function button(text, action, variant = "", symbol) {
  return h("button", {type:"button",class:`button ${variant}`, onclick:async event => {
    const node = event.currentTarget; node.disabled = true;
    try { await action(); } catch (error) { toast(error.message, true); } finally { node.disabled = false; }
  }}, symbol ? icon(symbol) : null, text);
}
export function badge(text, tone = "") { return h("span", {class:`badge ${tone}`}, text); }
export function tone(status) { return ["ready","ok","configured","active","enabled","won","SUPPORTED","completion_succeeded"].includes(status) ? "success" : ["error","failed","lost","completion_failed"].includes(status) ? "error" : "warning"; }
export function stamp(value) { return value ? new Date(value).toLocaleString([], {month:"short",day:"numeric",year:"numeric",hour:"2-digit",minute:"2-digit"}) : "Unavailable"; }
export function number(value) { return typeof value === "number" ? value.toLocaleString() : "—"; }
export function bytes(value) { return value < 1024 ? `${value} B` : value < 1024**2 ? `${(value/1024).toFixed(1)} KB` : `${(value/1024**2).toFixed(1)} MB`; }
export function toast(message, error = false) {
  const node = h("div", {class:`toast ${error ? "error" : ""}`,role:error?"alert":"status"}, message);
  document.getElementById("toasts").append(node); setTimeout(() => node.remove(), 6500);
}
export function heading(title, subtitle, ...actions) { return h("div",{class:"page-heading"},h("div",{},h("h1",{},title),h("p",{},subtitle)),h("div",{class:"heading-actions"},actions)); }
export function card(title, subtitle, body, action) { return h("section",{class:"card"},h("div",{class:"card-head"},h("div",{},h("h2",{},title),subtitle ? h("p",{},subtitle):null),action),body); }
export function notice(text, warning = false) { return h("div",{class:`notice ${warning?"warning":""}`},icon("info"),h("span",{},text)); }
export function empty(title, subtitle, symbol = "overview", action) { return h("div",{class:"empty-state"},h("div",{class:"empty-icon"},icon(symbol)),h("h3",{},title),h("p",{},subtitle),action); }
export function table(columns, rows) {
  return h("div",{class:"table-wrap"},h("table",{},h("thead",{},h("tr",{},columns.map(c => h("th",{scope:"col"},c)))),h("tbody",{},rows.map(cells => h("tr",{},cells.map(cell => h("td",{},cell)))))));
}
export function stat(title, value, note, symbol) { return h("div",{class:"stat"},h("div",{class:"stat-top"},title,h("span",{class:"stat-icon"},icon(symbol))),h("div",{class:"stat-value"},number(value)),h("div",{class:"stat-note"},note)); }
export function loader() { return h("div",{},h("div",{class:"skeleton line"}),h("div",{class:"stats-grid"},[1,2,3,4].map(()=>h("div",{class:"stat skeleton"}))),h("div",{class:"skeleton panel"})); }
export function field(label, name, value = "", options = {}) {
  const attrs = {name,value,"aria-label":label,required:options.required, maxlength:options.maxlength, ...options.attrs};
  const input = options.textarea ? h("textarea", {...attrs,rows:options.rows||4}) : options.select ? h("select",attrs,options.select.map(x=>h("option",{value:x.value,selected:x.value===value},x.label))) : h("input", {...attrs,type:options.type||"text"});
  if (options.textarea) input.value = value;
  return h("label",{class:`field ${options.wide?"span-2":""}`},h("span",{},label),input,options.help?h("small",{},options.help):null);
}
export function dialog(title, content, {submit, submitText = "Save changes", danger = false} = {}) {
  const box = h("dialog", {"aria-label":title});
  const form = h("form");
  const error = h("p",{class:"form-error",role:"alert",hidden:true});
  const close = () => { box.close(); box.remove(); };
  const cancel = button(submit ? "Cancel" : "Close",close);
  const save = submit ? h("button",{class:`button ${danger?"danger":"primary"}`,type:"submit"},submitText) : null;
  form.append(h("div",{class:"dialog-head"},h("h2",{},title),button("",close,"subtle small","close")),h("div",{class:"dialog-content"},content,error),h("div",{class:"dialog-footer"},cancel,save));
  box.append(form); document.body.append(box); box.showModal();
  box.addEventListener("cancel",()=>box.remove());
  if (submit) form.addEventListener("submit",async event=>{
    event.preventDefault(); error.hidden = true; save.disabled = true; cancel.disabled = true;
    try { await submit(new FormData(form), form); close(); }
    catch (failure) { error.textContent = failure.message; error.hidden = false; }
    finally { save.disabled = false; cancel.disabled = false; }
  });
  return {box,form,close};
}
export function confirmAction(title, message, action, label = "Confirm") { return dialog(title,h("p",{},message),{submit:action,submitText:label,danger:true}); }
export function pagination(page, total, size, change) { return h("div",{class:"pagination"},h("span",{},total?`Showing ${(page-1)*size+1}–${Math.min(page*size,total)} of ${total}`:"0 results"),h("div",{class:"actions"},h("button",{class:"button small",disabled:page<=1,onclick:()=>change(page-1)},"Previous"),h("button",{class:"button small",disabled:page*size>=total,onclick:()=>change(page+1)},"Next"))); }
export function search(value, apply, placeholder = "Search…") { return h("form",{class:"search-field",onsubmit:event=>{event.preventDefault();apply(event.currentTarget.elements.q.value);}},icon("search"),h("input",{name:"q",value,placeholder,"aria-label":placeholder,maxlength:120}),h("button",{type:"submit",class:"button subtle small"},"Search")); }
export function select(value, options, onChange, label) { return h("select",{value,"aria-label":label,onchange:event=>onChange(event.target.value)},options.map(item=>h("option",{value:item.value,selected:item.value===value},item.label))); }

export function chart(series, metric = "conversations") {
  const hasData = series.some(row => row[metric] > 0 || row.leads > 0);
  if (!hasData) return h("div",{class:"chart-empty"},icon("analytics"),h("strong",{},"Your activity will appear here"),h("p",{},"No conversations or leads recorded in this period."));
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns,"svg"); svg.setAttribute("viewBox","0 0 660 220");svg.setAttribute("class","chart-svg");svg.setAttribute("role","img");svg.setAttribute("aria-label",`${metric} and leads by UTC day`);
  const add = (name,attrs,text) => {const node=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);if(text!==undefined)node.textContent=text;svg.append(node);return node;};
  const max=Math.max(1,...series.map(x=>Math.max(x[metric],x.leads)));
  for(let i=0;i<5;i++){const y=20+i*40;add("line",{x1:35,y1:y,x2:650,y2:y,class:"grid"});add("text",{x:25,y:y+4,"text-anchor":"end"},Math.round(max*(1-i/4)));}
  for(const [key,cls] of [[metric,"line"],["leads","lead-line"]]){
    const points=series.map((row,i)=>`${35+i*615/Math.max(1,series.length-1)},${180-row[key]/max*160}`).join(" ");
    add("polyline",{points,class:cls});
  }
  [0,Math.floor((series.length-1)/2),series.length-1].forEach(i=>add("text",{x:35+i*615/Math.max(1,series.length-1),y:210,"text-anchor":i===0?"start":i===series.length-1?"end":"middle"},new Date(series[i].date+"T00:00:00Z").toLocaleDateString([], {month:"short",day:"numeric",timeZone:"UTC"})));
  return svg;
}
