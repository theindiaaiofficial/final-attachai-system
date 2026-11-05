import { api, saveFile } from "./api.js";
import { h, button, badge, tone, heading, empty, table, field, dialog, confirmAction, toast, pagination, search, select, stamp, bytes, notice } from "./ui.js";

const base = context => `/admin/clients/${encodeURIComponent(context.tenant)}`;
function noTenant(context, title) { return h("div",{},heading(title,"Manage this workspace’s tenant-scoped records."),h("section",{class:"card"},empty("Create a client first","These records always belong to a specific client. Add a client to get started.","clients",button("Go to clients",()=>context.navigate("clients"),"primary")))); }

export async function conversationsView(context) {
  if(!context.tenant)return noTenant(context,"Conversations");
  const f=context.filters.conversations||={q:"",page:1};
  const update=changes=>{Object.assign(f,{page:1},changes);context.refresh();};
  const result=await api(`${base(context)}/sessions?${new URLSearchParams({q:f.q,page:f.page,page_size:15})}`);
  const panel=h("section",{class:"card"},h("div",{class:"toolbar"},search(f.q,q=>update({q}),"Search title or session ID…"),badge(`${result.total} conversations`)));
  panel.append(result.items.length?table(["Conversation","Messages","Created","Last activity",""],result.items.map(row=>[
    h("div",{class:"cell-wrap"},h("button",{class:"row-link",onclick:()=>openConversation(context,row.session_id).catch(error=>toast(error.message,true))},row.title||"Untitled conversation"),h("div",{class:"mono text-muted"},row.session_id.slice(0,8))),String(row.message_count??"—"),stamp(row.created_at),stamp(row.updated_at),h("div",{class:"actions"},button("View",()=>openConversation(context,row.session_id),"small")),
  ])):empty("No conversations found","Completed chat sessions for this client will appear here.","conversations"));
  panel.append(pagination(f.page,result.total,15,page=>update({page})));
  return h("div",{},heading("Conversations","Explore tenant-scoped history, route decisions, and sources.",context.tenantSelector()),panel);
}

async function openConversation(context, id) {
  const item=await api(`${base(context)}/sessions/${id}`);
  const content=h("div",{},h("p",{class:"mono text-muted"},`${context.tenantName()} · ${item.session_id}`));
  if(!item.messages.length)content.append(empty("No messages yet","This session has not recorded any messages.","conversations"));
  item.messages.forEach(message=>{
    const node=h("article",{class:`message ${message.role}`},h("div",{class:"message-head"},h("strong",{},message.role==="assistant"?"Assistant":"Visitor"),h("time",{},stamp(message.created_at))),h("p",{class:"message-text"},message.content));
    if(message.route)node.append(h("div",{class:"toolbar-group section-label"},badge(message.route),message.evidence_status?badge(message.evidence_status):null));
    for(const citation of message.citations||[])node.append(h("div",{class:"citation"},h("strong",{},`${citation.filename}${citation.page?` · page ${citation.page}`:""} [${citation.source_id}]`),citation.excerpt?h("blockquote",{},citation.excerpt):null));
    content.append(node);
  });
  const box=dialog(item.title||"Conversation",content);
  content.append(button("Delete conversation",()=>confirmAction("Delete this conversation?","Its message history and saved citations will be removed. This cannot be undone.",async()=>{await api(`${base(context)}/sessions/${id}`,{method:"DELETE"});box.close();context.refresh();toast("Conversation deleted.");},"Delete conversation"),"danger","trash"));
}

export async function knowledgeView(context) {
  if(!context.tenant)return noTenant(context,"Knowledge base");
  const files=await api(`${base(context)}/knowledge`);
  const f=context.filters.knowledge||={q:"",results:[]};
  const upload=h("form",{class:"upload-zone"},h("div",{},h("h3",{},"Give your assistant the right knowledge"),h("p",{},"TXT, Markdown, PDF, DOCX, CSV, JSON · Up to 10 files, 10 MB each")),h("div",{class:"toolbar-group"},h("input",{type:"file",name:"files",multiple:true,required:true,accept:".txt,.md,.pdf,.docx,.csv,.json","aria-label":"Knowledge files"}),h("button",{type:"submit",class:"button primary"},"Upload & index")));
  upload.addEventListener("submit",async event=>{
    event.preventDefault(); const input=upload.elements.files;
    if(input.files.length>10||[...input.files].some(file=>file.size>10*1024*1024)){toast("Upload at most 10 files of up to 10 MB each.",true);return;}
    const body=new FormData();[...input.files].forEach(file=>body.append("files",file));
    const submit=upload.querySelector("button");submit.disabled=true;submit.textContent="Processing…";
    try {const result=await api(`${base(context)}/knowledge`,{method:"POST",body,timeout:180000});f.results=result.items;const failed=f.results.some(x=>x.status==="error");toast(failed?"Some files could not be indexed. Review the results.":"Knowledge indexed successfully.",failed);context.refresh();}
    catch(error){toast(error.message,true);}
    finally{submit.disabled=false;submit.textContent="Upload & index";}
  });
  const filtered=files.filter(file=>file.filename.toLowerCase().includes(f.q.toLowerCase()));
  const panel=h("section",{class:"card"},h("div",{class:"toolbar"},search(f.q,q=>{f.q=q;context.refresh();},"Search documents…"),badge(`${files.length} documents`)));
  panel.append(filtered.length?table(["Document","Status","Size","Chunks","Updated",""],filtered.map(file=>[
    h("div",{class:"cell-wrap"},h("strong",{},file.filename),file.error?h("p",{class:"form-error"},file.error):h("small",{class:"mono"},`SHA-256 ${file.content_hash.slice(0,12)}…`)),badge(file.status,tone(file.status)),bytes(file.size),String(file.chunks??"—"),stamp(file.updated_at),h("div",{class:"actions"},button("Delete",()=>confirmAction("Delete this document?","Its stored source and tenant-scoped index records will be removed.",async()=>{await api(`${base(context)}/knowledge/${encodeURIComponent(file.filename)}`,{method:"DELETE"});toast("Document deleted.");context.refresh();},"Delete document"),"small danger","trash")),
  ])):empty("No documents found","Upload tenant-specific files to ground business answers in your source material.","knowledge"));
  const rebuild=button("Rebuild index",()=>confirmAction("Rebuild stored knowledge?","Stored sources will be re-read and embedded using the active embedding configuration. The result will report actual completion or per-file errors.",async()=>{const result=await api(`${base(context)}/knowledge/rebuild`,{method:"POST",timeout:180000});f.results=result.items;toast(result.status==="completed"?"Rebuild completed.":"Rebuild completed with errors.",result.status!=="completed");context.refresh();},"Rebuild index"),"","refresh");
  rebuild.disabled=!files.length;
  return h("div",{},heading("Knowledge base","Curate the source of truth for each assistant.",context.tenantSelector(),rebuild),notice("Document text is processed by the configured embedding provider. Scanned/image-only PDFs require external OCR."),upload,
    f.results.length?h("section",{class:"card"},h("div",{class:"card-head"},h("h2",{},"Latest processing results")),table(["File","Result","Details"],f.results.map(item=>[item.filename,badge(item.status,tone(item.status)),h("span",{class:"cell-wrap"},item.error||`${item.chunks??0} chunks indexed`)]))):null,panel);
}

export async function leadsView(context) {
  if(!context.tenant)return noTenant(context,"Leads");
  const f=context.filters.leads||={q:"",status:"all",page:1};
  const update=changes=>{Object.assign(f,{page:1},changes);context.refresh();};
  const rows=await api(`${base(context)}/leads?${new URLSearchParams({q:f.q,status:f.status})}`);
  const panel=h("section",{class:"card"},h("div",{class:"toolbar"},h("div",{class:"toolbar-group"},search(f.q,q=>update({q}),"Search leads…"),select(f.status,["all","new","contacted","qualified","won","lost"].map(value=>({value,label:value==="all"?"All statuses":value[0].toUpperCase()+value.slice(1)})),status=>update({status}),"Lead status")),badge(`${rows.length} leads`)));
  const display=rows.slice((f.page-1)*15,f.page*15);
  panel.append(display.length?table(["Lead","Contact","Status","Assignee","Received",""],display.map(row=>[
    h("div",{class:"cell-primary"},h("span",{class:"client-avatar"},(row.data.name||"L").slice(0,2).toUpperCase()),h("div",{},h("strong",{},row.data.name),h("small",{class:"truncate"},row.data.requirement||row.data.message))),h("div",{},h("div",{},row.data.email||"No email"),h("small",{},row.data.phone||"No phone")),badge(row.status,tone(row.status)),row.assignee||"Unassigned",stamp(row.created_at),button("View lead",()=>openLead(context,row.id),"small","arrow"),
  ])):empty("No leads found","Contact requests captured by this client’s widget will appear here.","leads"));
  panel.append(pagination(f.page,rows.length,15,page=>update({page})));
  return h("div",{},heading("Leads","Turn visitor interest into meaningful conversations.",context.tenantSelector(),button("Export CSV",async()=>{saveFile(await api(`${base(context)}/leads.csv`,{download:true}),"orbit-leads.csv");toast("CSV exported.");},"","download")),panel);
}

async function openLead(context,id){
  const row=await api(`${base(context)}/leads/${id}`);
  const body=h("div",{},h("p",{class:"text-muted"},`Received ${stamp(row.created_at)} · ${context.tenantName()}`),h("div",{class:"form-grid form-section"},
    field("Name","name",row.data.name||"",{required:true,maxlength:120}),field("Email","email",row.data.email||"",{type:"email",maxlength:320}),field("Phone","phone",row.data.phone||"",{maxlength:40}),field("Status","status",row.status,{select:["new","contacted","qualified","won","lost"].map(value=>({value,label:value}))}),field("Assignee","assignee",row.assignee||"",{maxlength:120}),field("Requirement / message","requirement",row.data.requirement||row.data.message||"",{textarea:true,wide:true,maxlength:2000}),field("Internal notes","notes",row.notes||"",{textarea:true,wide:true,maxlength:10000})
  ));
  if(row.conversation_id)body.append(button("View linked conversation",()=>openConversation(context,row.conversation_id),"","conversations"));
  dialog("Lead details",body,{submitText:"Update lead",submit:async data=>{
    await api(`${base(context)}/leads/${id}`,{method:"PATCH",body:{status:data.get("status"),assignee:data.get("assignee")||null,notes:data.get("notes"),data:{...row.data,name:data.get("name"),email:data.get("email"),phone:data.get("phone"),requirement:data.get("requirement")}}});
    toast("Lead updated.");context.refresh();
  }});
}
