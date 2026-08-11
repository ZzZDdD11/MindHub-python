function pgKnowledgeLifecycle(){
  const data=state.data.knowledgeLifecycle||{};
  const candidates=data.candidates||[];
  const cards=data.cards||[];
  return `<div class="page-shell"><div class="page-header"><div><div class="page-title">知识沉淀</div><div class="page-subtitle">人工审核 · 草稿编辑 · 版本化发布 · Wiki 与图谱投影</div></div></div>
  <div class="card" style="padding:16px;margin-bottom:16px"><div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap"><div class="input-group" style="margin:0;min-width:260px;flex:1"><label class="input-label">管理员密钥</label><input class="input" type="password" id="knowledgeAdminKey" value="${esc(data.adminKey||'')}" placeholder="仅保留在当前页面内存" oninput="state.data.knowledgeLifecycle.adminKey=this.value"></div><button class="btn btn-primary" onclick="loadKnowledgeLifecycle()">${I.refresh}加载待审候选</button></div>${data.error?`<div style="margin-top:10px;color:var(--destructive);font-size:13px">${esc(data.error)}</div>`:''}</div>
  <div class="card" style="padding:16px;margin-bottom:16px"><div style="font-weight:700;margin-bottom:12px">待审核 Candidate</div>${candidates.length?candidates.map(candidate=>`<div style="border-top:1px solid var(--border);padding:12px 0"><div style="display:flex;justify-content:space-between;gap:12px;align-items:start"><div><div style="font-weight:600">${esc(candidate.record.model||'conversation')}</div><div style="font-size:12px;color:var(--muted-foreground);margin-top:4px">${esc(candidate.record.trace_id||'')} · ${esc(candidate.record.completed_at||'')}</div><div style="font-size:13px;margin-top:8px;white-space:pre-wrap">${esc((candidate.record.request_payload||'').slice(0,360))}</div></div><div style="display:flex;gap:8px;flex-shrink:0"><button class="btn btn-secondary btn-sm" onclick="reviewKnowledgeCandidate('${candidate.candidate.id}','reject')">拒绝</button><button class="btn btn-primary btn-sm" onclick="reviewKnowledgeCandidate('${candidate.candidate.id}','approve')">通过并创建草稿</button></div></div></div>`).join(''):`<div style="color:var(--muted-foreground);font-size:13px">暂无待审核 Candidate</div>`}</div>
  <div class="card" style="padding:16px"><div style="font-weight:700;margin-bottom:12px">已发布知识卡</div>${cards.length?cards.map(item=>`<div style="border-top:1px solid var(--border);padding:10px 0"><div style="display:flex;justify-content:space-between;gap:10px"><div><div style="font-weight:600">${esc(item.version.title)}</div><div style="font-size:12px;color:var(--muted-foreground);margin-top:3px">KB: ${esc(item.version.kb_id)} · v${item.version.version}</div></div><div style="display:flex;gap:8px"><button class="btn btn-secondary btn-sm" onclick="showKnowledgeDraft('${item.card.candidate_id}')">创建修订</button><button class="btn btn-secondary btn-sm" onclick="viewKnowledgeProjections('${item.version.kb_id}')">Wiki / 图谱</button></div></div></div>`).join(''):`<div style="color:var(--muted-foreground);font-size:13px">暂无已发布知识卡</div>`}</div></div>`;
}

async function knowledgeAdminApi(path,opts={}){
  const key=state.data.knowledgeLifecycle.adminKey||'';
  const headers={'Content-Type':'application/json','X-Admin-API-Key':key,...(opts.headers||{})};
  try{const r=await fetch('/api/v1/admin/knowledge'+path,{...opts,headers});const body=await r.json();if(!r.ok)return{code:'ERR',info:body.detail||body.info||'请求失败'};return body;}catch(e){return{code:'ERR',info:'网络错误：'+e.message};}
}

async function loadKnowledgeLifecycle(){
  const data=state.data.knowledgeLifecycle;
  const [candidateResult,cardResult,kbResult]=await Promise.all([knowledgeAdminApi('/candidates'),knowledgeAdminApi('/cards'),api('/kb')]);
  data.error=candidateResult.code==='0000'?null:(candidateResult.info||'无法加载候选');
  data.candidates=candidateResult.code==='0000'?(candidateResult.data||[]):[];
  data.cards=cardResult.code==='0000'?(cardResult.data||[]):[];
  if(kbResult.code==='0000')state.data.kb=kbResult.data||[];
  updatePage('knowledgeLifecycle');
}

async function reviewKnowledgeCandidate(id,action){
  const note=prompt(action==='approve'?'审核说明（可选）':'拒绝原因（可选）');if(note===null)return;
  const r=await knowledgeAdminApi('/candidates/'+id+'/'+action,{method:'POST',body:JSON.stringify({note})});
  if(r.code!=='0000'){toast(r.info||'审核失败','error');return;}
  if(action==='approve')await showKnowledgeDraft(id);else{toast('已拒绝');loadKnowledgeLifecycle();}
}

async function showKnowledgeDraft(candidateId){
  const ai=await knowledgeAdminApi('/candidates/'+candidateId+'/drafts/ai',{method:'POST'});
  const draft=ai.code==='0000'?ai.data:null;
  showModal(`<div class="modal-header"><div class="modal-title">${draft?'AI 草稿':'手工草稿'}</div></div><div class="modal-body"><div class="input-group"><label class="input-label">标题</label><input class="input" id="lcTitle" value="${esc(draft?.title||'')}"></div><div class="input-group"><label class="input-label">摘要</label><textarea class="input" id="lcSummary" rows="3">${esc(draft?.summary||'')}</textarea></div><div class="input-group"><label class="input-label">正文</label><textarea class="input" id="lcContent" rows="10">${esc(draft?.content||'')}</textarea></div><div class="input-group"><label class="input-label">标签（逗号分隔）</label><input class="input" id="lcTags" value="${esc((draft?.tags||[]).join(','))}"></div><div class="input-group"><label class="input-label">目标知识库</label><select class="input" id="lcKb">${(state.data.kb||[]).map(k=>`<option value="${esc(k.id)}">${esc(k.name)}</option>`).join('')}</select></div>${!draft?`<div style="font-size:12px;color:var(--muted-foreground)">AI 草稿不可用，可手工填写后发布。</div>`:''}</div><div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="saveAndPublishKnowledgeDraft('${candidateId}','${draft?.id||''}')">发布</button></div>`);
}

async function saveAndPublishKnowledgeDraft(candidateId,draftId){
  const payload={title:document.getElementById('lcTitle').value,summary:document.getElementById('lcSummary').value,content:document.getElementById('lcContent').value,tags:document.getElementById('lcTags').value.split(',').map(v=>v.trim()).filter(Boolean)};
  let id=draftId;
  let r;
  if(id)r=await knowledgeAdminApi('/drafts/'+id,{method:'PUT',body:JSON.stringify(payload)});else r=await knowledgeAdminApi('/candidates/'+candidateId+'/drafts/manual',{method:'POST',body:JSON.stringify(payload)});
  if(r.code!=='0000'){toast(r.info||'保存草稿失败','error');return;}
  id=r.data.id;
  r=await knowledgeAdminApi('/drafts/'+id+'/publish',{method:'POST',body:JSON.stringify({kb_id:document.getElementById('lcKb').value})});
  if(r.code!=='0000'){toast(r.info||'发布失败','error');return;}
  closeModal();toast('知识卡已发布');loadKnowledgeLifecycle();
}

async function viewKnowledgeProjections(kbId){
  const [wiki,graph]=await Promise.all([knowledgeAdminApi('/wiki/'+kbId),knowledgeAdminApi('/graph/'+kbId)]);
  if(wiki.code!=='0000'||graph.code!=='0000'){toast((wiki.info||graph.info||'读取投影失败'),'error');return;}
  const pages=wiki.data||[];const edges=graph.data||[];
  showModal(`<div class="modal-header"><div class="modal-title">Wiki 与知识图谱</div></div><div class="modal-body"><div style="font-weight:600;margin-bottom:8px">Wiki 页面</div>${pages.length?pages.map(p=>`<div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px"><div style="font-weight:600">${esc(p.title)}</div><div style="font-size:12px;color:var(--muted-foreground);margin:4px 0">/${esc(p.slug)}</div><div style="font-size:13px;white-space:pre-wrap;max-height:140px;overflow:auto">${esc(p.content)}</div></div>`).join(''):'<div style="color:var(--muted-foreground);font-size:13px">暂无 Wiki 投影</div>'}<div style="font-weight:600;margin:16px 0 8px">图谱关系</div>${edges.length?edges.map(e=>`<div style="font-size:13px;padding:8px 0;border-top:1px solid var(--border)">${esc(e.source_name)} — ${esc(e.relation_type)} → ${esc(e.target_name)} <span style="color:var(--muted-foreground)">(${Number(e.confidence||0).toFixed(2)})</span><div style="font-size:12px;color:var(--muted-foreground);margin-top:3px">${esc(e.evidence||'')}</div></div>`).join(''):'<div style="color:var(--muted-foreground);font-size:13px">暂无图谱关系；配置知识流水线模型后发布即可自动抽取。</div>'}</div><div class="modal-footer"><button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
}
