import {useEffect,useState} from 'react';
import {
  Activity,Bot,Boxes,ChevronRight,CircleHelp,Command,Cpu,Folder,Globe,LayoutDashboard,
  MessageSquare,Plus,Search,Send,Settings,ShieldCheck,Sparkles,Terminal,Workflow,Plug,
  RefreshCw,Check,X,Server,PanelLeftClose,Zap,Clock3,ArrowUpRight,ArrowLeft,ArrowRight,
  RotateCw,Camera,Download,ExternalLink,Trash2,Shield,Eye,
  AlertTriangle,Play,Pause,Calendar,Brain,Edit2,Archive,Repeat,StopCircle
} from 'lucide-react';

const API = 'http://127.0.0.1:8000/api';
type Tool = {name:string;description:string;source:string;risk:string};
type Msg = {role:string;content:string};

const nav = [
  ['Overview',LayoutDashboard],
  ['Chat',MessageSquare],
  ['Tool Registry',Boxes],
  ['Models',Bot],
  ['Activity Log',Clock3],
  ['Settings',Settings],
  ['System',Activity],
  ['Files',Folder],
  ['Browser',Globe],
  ['Terminal',Terminal],
  ['Tasks',Workflow],
  ['Memory',Brain]
];

export default function App() {
  const [page,P] = useState('Overview');
  const [tools,T] = useState<Tool[]>([]);
  const [servers,S] = useState<any[]>([]);
  const [providers,V] = useState<any>({});
  const [audit,A] = useState<any[]>([]);
  const [approvals,Q] = useState<any[]>([]);
  const [system,Y] = useState<any>({});
  const [msgs,M] = useState<Msg[]>([]);
  const [text,Xt] = useState('');
  const [busy,B] = useState(false);
  const [cid,C] = useState<number|null>(null);
  const [provider,Pr] = useState('groq');
  const [model,Mo] = useState('openai/gpt-oss-20b');
  const [key,K] = useState('');
  const [kp,Kp] = useState('gemini');
  const [name,N] = useState('');
  const [transport,Tr] = useState('stdio');
  const [cmd,Cm] = useState('');
  const [args,Ar] = useState('');
  const [url,U] = useState('');
  const [notice,Z] = useState('');

  // Resilience & Fallback State
  const [infStatus, setInfStatus] = useState<string>('');
  const [autoFallback, setAutoFallback] = useState<boolean>(false);
  const [fbProvider, setFbProvider] = useState<string>('gemini');
  const [fbModel, setFbModel] = useState<string>('gemini-2.5-flash');

  // Browser Workspace State
  const [bStatus, setBStatus] = useState<any>({ is_running: false, tab_count: 0 });
  const [bTabs, setBTabs] = useState<any[]>([]);
  const [bUrl, setBUrl] = useState('');
  const [bScreenshot, setBScreenshot] = useState('');
  const [bDownloads, setBDownloads] = useState<any[]>([]);
  const [bRules, setBRules] = useState<any[]>([]);
  const [bQuery, setBQuery] = useState('');
  const [bResults, setBResults] = useState<any[]>([]);
  const [rType, setRType] = useState('allowlist_domain');
  const [rPattern, setRPattern] = useState('');
  const [bLoading, setBLoading] = useState(false);

  // Phase 5 State: Emergency, Memory, Tasks, Scheduler
  const [emergency, setEmergency] = useState<any>({ is_stopped: false, reason: '', stopped_at: '' });
  const [showStopModal, setShowStopModal] = useState<boolean>(false);
  const [tasksTab, setTasksTab] = useState<'plans' | 'schedules'>('plans');

  // Memories
  const [memories, setMemories] = useState<any[]>([]);
  const [memCat, setMemCat] = useState<string>('all');
  const [memSearch, setMemSearch] = useState<string>('');
  const [showAddMem, setShowAddMem] = useState<boolean>(false);
  const [newMemCat, setNewMemCat] = useState<string>('user_preference');
  const [newMemKey, setNewMemKey] = useState<string>('');
  const [newMemContent, setNewMemContent] = useState<string>('');
  const [editingMemId, setEditingMemId] = useState<number | null>(null);
  const [editMemCat, setEditMemCat] = useState<string>('user_preference');
  const [editMemKey, setEditMemKey] = useState<string>('');
  const [editMemContent, setEditMemContent] = useState<string>('');

  // Tasks & Plans
  const [tasksList, setTasksList] = useState<any[]>([]);
  const [newPlanPrompt, setNewPlanPrompt] = useState<string>('');
  const [isPlanning, setIsPlanning] = useState<boolean>(false);

  // Schedules
  const [schedulesList, setSchedulesList] = useState<any[]>([]);
  const [showAddSched, setShowAddSched] = useState<boolean>(false);
  const [schedName, setSchedName] = useState<string>('');
  const [schedPrompt, setSchedPrompt] = useState<string>('');
  const [schedType, setSchedType] = useState<string>('daily');
  const [schedInterval, setSchedInterval] = useState<number>(3600);
  const [openHistoryId, setOpenHistoryId] = useState<string | null>(null);
  const [schedRuns, setSchedRuns] = useState<{[key: string]: any[]}>({});

  async function req(path:string,init?:RequestInit) {
    let r = await fetch(API+path,{headers:{'Content-Type':'application/json'},...init});
    let d = await r.json();
    if(!r.ok) throw Error(d.detail||'Request failed');
    return d;
  }

  async function refresh() {
    try {
      let[t,s,v,a,q,y,stg,emg] = await Promise.all([
        req('/tools'),req('/mcp/servers'),req('/providers'),req('/audit'),req('/approvals'),req('/system'),req('/settings'),req('/emergency/status')
      ]);
      T(t);S(s);V(v);A(a);Q(q);Y(y);
      if (emg) setEmergency(emg);
      if (stg) {
        setAutoFallback(Boolean(stg.auto_provider_fallback));
        setFbProvider(stg.fallback_provider || 'gemini');
        setFbModel(stg.fallback_model || 'gemini-2.5-flash');
      }
      if (page === 'Browser') {
        await loadBrowserData();
      }
      if (page === 'Memory') {
        await loadMemories();
      }
      if (page === 'Tasks') {
        await loadTasks();
        await loadSchedules();
      }
      if (cid) {
        try {
          let latestMsgs = await req(`/conversations/${cid}/messages`);
          if (Array.isArray(latestMsgs)) {
            let mapped = latestMsgs.map((m: any) => ({ role: m.role, content: m.content }));
            M(prev => {
              if (prev.length !== mapped.length || JSON.stringify(prev) !== JSON.stringify(mapped)) {
                return mapped;
              }
              return prev;
            });
          }
        } catch (_) {}
      }
    } catch(e:any) {
      Z(e.message);
    }
  }

  // Phase 5 Action Functions
  async function triggerEmergency() {
    try {
      let st = await req('/emergency/stop', { method: 'POST', body: JSON.stringify({ reason: 'User initiated emergency stop from dashboard' }) });
      setEmergency(st);
      setShowStopModal(false);
      Z('GLOBAL EMERGENCY STOP ENGAGED: All tool execution and background tasks paused.');
      await refresh();
    } catch (e: any) {
      Z(`Failed to engage emergency stop: ${e.message}`);
    }
  }

  async function clearEmergency() {
    try {
      let st = await req('/emergency/resume', { method: 'POST' });
      setEmergency(st);
      Z('Global Emergency Stop cleared. Normal operations resumed.');
      await refresh();
    } catch (e: any) {
      Z(`Failed to clear emergency stop: ${e.message}`);
    }
  }

  async function loadMemories() {
    try {
      let q = memSearch.trim() ? `&query=${encodeURIComponent(memSearch.trim())}` : '';
      let cat = memCat !== 'all' ? `&category=${memCat}` : '';
      let res = await req(`/memories?status=active${cat}${q}`);
      setMemories(Array.isArray(res) ? res : []);
    } catch (e: any) {
      // Ignored if table not populated
    }
  }

  async function saveMemory() {
    if (!newMemContent.trim()) return;
    try {
      await req('/memories', {
        method: 'POST',
        body: JSON.stringify({
          category: newMemCat,
          key: newMemKey.trim() || null,
          content: newMemContent.trim(),
          source: 'user_explicit'
        })
      });
      setShowAddMem(false);
      setNewMemContent('');
      setNewMemKey('');
      Z('Memory saved successfully.');
      await loadMemories();
    } catch (e: any) {
      Z(`Memory error: ${e.message}`);
    }
  }

  function startEditMem(m: any) {
    setEditingMemId(m.id);
    setEditMemCat(m.category);
    setEditMemKey(m.key || '');
    setEditMemContent(m.content);
  }

  async function updateMemory() {
    if (!editingMemId || !editMemContent.trim()) return;
    try {
      await req(`/memories/${editingMemId}`, {
        method: 'PUT',
        body: JSON.stringify({
          category: editMemCat,
          key: editMemKey.trim() || null,
          content: editMemContent.trim()
        })
      });
      setEditingMemId(null);
      await loadMemories();
      Z(`Memory #${editingMemId} updated successfully.`);
    } catch (e: any) {
      Z(`Failed to update memory: ${e.message}`);
    }
  }

  async function archiveMem(id: number) {
    try {
      await req(`/memories/${id}/archive`, { method: 'POST' });
      await loadMemories();
      Z(`Memory #${id} archived.`);
    } catch (e: any) {
      Z(`Failed to archive memory: ${e.message}`);
    }
  }

  async function deleteMem(id: number) {
    try {
      await req(`/memories/${id}`, { method: 'DELETE' });
      await loadMemories();
      Z(`Memory #${id} deleted.`);
    } catch (e: any) {
      Z(`Failed to delete memory: ${e.message}`);
    }
  }

  async function loadTasks() {
    try {
      let res = await req('/tasks');
      setTasksList(Array.isArray(res) ? res : []);
    } catch (e: any) {
      // Ignored
    }
  }

  async function createPlan() {
    if (!newPlanPrompt.trim()) return;
    setIsPlanning(true);
    try {
      let res = await req('/tasks/plan', {
        method: 'POST',
        body: JSON.stringify({ user_request: newPlanPrompt.trim() })
      });
      setNewPlanPrompt('');
      Z(`Plan '${res.title}' created (${res.total_steps} steps).`);
      await loadTasks();
    } catch (e: any) {
      Z(`Planning failed: ${e.message}`);
    } finally {
      setIsPlanning(false);
    }
  }

  async function executePlan(taskId: string) {
    try {
      Z(`Executing plan ${taskId}...`);
      await req(`/tasks/${taskId}/execute`, { method: 'POST' });
      await loadTasks();
    } catch (e: any) {
      Z(`Execution failed: ${e.message}`);
    }
  }

  async function pauseTask(taskId: string) {
    try {
      await req(`/tasks/${taskId}/pause`, { method: 'POST' });
      await loadTasks();
    } catch (e: any) {
      Z(`Pause failed: ${e.message}`);
    }
  }

  async function resumeTask(taskId: string) {
    try {
      await req(`/tasks/${taskId}/resume`, { method: 'POST' });
      await loadTasks();
    } catch (e: any) {
      Z(`Resume failed: ${e.message}`);
    }
  }

  async function cancelTask(taskId: string) {
    try {
      await req(`/tasks/${taskId}/cancel`, { method: 'POST' });
      await loadTasks();
    } catch (e: any) {
      Z(`Cancel failed: ${e.message}`);
    }
  }

  async function retryTaskStep(taskId: string, stepId: string) {
    try {
      await req(`/tasks/${taskId}/steps/${stepId}/retry`, { method: 'POST' });
      await loadTasks();
    } catch (e: any) {
      Z(`Retry failed: ${e.message}`);
    }
  }

  async function recoverTaskStep(taskId: string, stepId: string, resolution: 'resolve' | 'skip' | 'retry') {
    try {
      await req(`/tasks/${taskId}/steps/${stepId}/recover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolution, notes: `Manual recovery action: ${resolution}` }),
      });
      await loadTasks();
    } catch (e: any) {
      Z(`Manual recovery failed: ${e.message}`);
    }
  }

  async function loadSchedules() {
    try {
      let res = await req('/schedules');
      setSchedulesList(Array.isArray(res) ? res : []);
    } catch (e: any) {
      // Ignored
    }
  }

  async function toggleSched(schedId: string, enabled: boolean) {
    try {
      await req(`/schedules/${schedId}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled: !enabled })
      });
      await loadSchedules();
    } catch (e: any) {
      Z(`Toggle failed: ${e.message}`);
    }
  }

  async function deleteSched(schedId: string) {
    try {
      await req(`/schedules/${schedId}`, { method: 'DELETE' });
      await loadSchedules();
      Z(`Schedule deleted.`);
    } catch (e: any) {
      Z(`Delete failed: ${e.message}`);
    }
  }

  async function toggleScheduleHistory(id: string) {
    if (openHistoryId === id) {
      setOpenHistoryId(null);
      return;
    }
    setOpenHistoryId(id);
    try {
      let runs = await req(`/schedules/${id}/history`);
      setSchedRuns(prev => ({...prev, [id]: Array.isArray(runs) ? runs : []}));
    } catch (e: any) {
      // Ignored
    }
  }

  async function saveSchedule() {
    if (!schedName.trim() || !schedPrompt.trim()) return;
    try {
      await req('/schedules', {
        method: 'POST',
        body: JSON.stringify({
          task_name: schedName.trim(),
          user_request: schedPrompt.trim(),
          schedule_type: schedType,
          interval_seconds: Number(schedInterval) || 3600
        })
      });
      setShowAddSched(false);
      setSchedName('');
      setSchedPrompt('');
      Z('Schedule created successfully.');
      await loadSchedules();
    } catch (e: any) {
      Z(`Failed to create schedule: ${e.message}`);
    }
  }

  async function toggleAutoFallback(enabled: boolean) {
    try {
      let res = await req('/settings', {
        method: 'POST',
        body: JSON.stringify({ auto_provider_fallback: enabled, fallback_provider: fbProvider, fallback_model: fbModel })
      });
      setAutoFallback(Boolean(res.auto_provider_fallback));
      Z(enabled ? 'Auto Provider Fallback enabled (will failover to Gemini if Groq limits).' : 'Auto Provider Fallback disabled.');
    } catch (e: any) {
      Z(`Failed to update fallback setting: ${e.message}`);
    }
  }

  async function loadBrowserData() {
    try {
      let [st, tb, dl, rl] = await Promise.all([
        req('/browser/status'),
        req('/browser/tabs'),
        req('/browser/downloads'),
        req('/browser/rules')
      ]);
      setBStatus(st);
      setBTabs(tb);
      setBDownloads(dl);
      setBRules(rl);
      if (st.active_url && st.active_url !== 'about:blank' && !bUrl) {
        setBUrl(st.active_url);
      }
    } catch (e: any) {
      // Ignored if browser not started yet
    }
  }

  useEffect(() => {
    refresh();
    let i = setInterval(refresh, 10000);
    return () => clearInterval(i);
  }, [page, memCat, memSearch]);

  async function summarizeChat() {
    if (!cid) {
      Z('No active conversation to summarize.');
      return;
    }
    setInfStatus('Summarizing conversation decisions and outcomes into memory...');
    try {
      await req(`/conversations/${cid}/summarize?provider=${provider}&model=${encodeURIComponent(model)}`, {
        method: 'POST'
      });
      setInfStatus('');
      Z(`Conversation #${cid} summarized and saved to memory.`);
      await loadMemories();
    } catch (e: any) {
      setInfStatus(`Summarization failed: ${e.message}`);
      Z(`Summarization failed: ${e.message}`);
    }
  }

  function startNewChat() {
    C(null);
    M([]);
    setInfStatus('');
  }

  async function send() {
    if(!text.trim()||busy) return;
    let m = text;
    Xt('');
    M(x=>[...x,{role:'user',content:m}]);
    B(true);
    setInfStatus(`Sending request to ${provider.toUpperCase()} (${model})...`);
    try {
      let d = await req('/chat',{method:'POST',body:JSON.stringify({message:m,conversation_id:cid,provider,model})});
      C(d.conversation_id);
      M(x=>[...x,{role:'assistant',content:d.reply}]);
      if (d.fallback_occurred) {
        setInfStatus(`Notice: Switched to ${d.provider_used.toUpperCase()} fallback due to rate limits.`);
        Z(`Rate limit reached on ${d.fallback_from}; successfully completed with ${d.provider_used} fallback.`);
      } else {
        setInfStatus('');
      }
    } catch(e:any) {
      setInfStatus(`Request failed: ${e.message}`);
      M(x=>[...x,{role:'assistant',content:'Request failed: '+e.message}]);
    } finally {
      B(false);
      setTimeout(() => setInfStatus(''), 8000);
    }
  }

  async function add() {
    try {
      let d = transport==='stdio'
        ? await req('/mcp/stdio',{method:'POST',body:JSON.stringify({name,command:cmd,args:args.split('\n').map((x:string)=>x.trim()).filter(Boolean),env:{}})})
        : await req('/mcp/http',{method:'POST',body:JSON.stringify({name,url})});
      Z(`Server '${d.name}' added. Status: ${d.status}`);
      N('');Cm('');Ar('');U('');
      await refresh();
    } catch(e:any) {
      Z(e.message);
    }
  }

  async function toggleServer(sid:string,connect:boolean) {
    try {
      if(connect){
        await req(`/mcp/servers/${sid}/connect`,{method:'POST'});
        Z('Connected MCP server.');
      } else {
        await req(`/mcp/servers/${sid}/disconnect`,{method:'POST'});
        Z('Disconnected MCP server.');
      }
      await refresh();
    } catch(e:any) {
      Z(e.message);
    }
  }

  async function removeServer(sid:string) {
    try {
      await req(`/mcp/servers/${sid}`,{method:'DELETE'});
      Z('Removed MCP server.');
      await refresh();
    } catch(e:any) {
      Z(e.message);
    }
  }

  async function save() {
    try {
      await req('/providers/key',{method:'POST',body:JSON.stringify({provider:kp,api_key:key})});
      K('');
      Z('Saved locally. Restart backend to load the key.');
    } catch(e:any) {
      Z(e.message);
    }
  }

  async function decide(id:number,approve:boolean) {
    try {
      let d = await req(`/approvals/${id}/decision?approve=${approve}`,{method:'POST'});
      if(d.status==='executed') {
        Z(`Approval #${id} executed successfully.`);
      } else if(d.status==='rejected') {
        Z(`Approval #${id} rejected.`);
      } else if(d.status==='failed') {
        Z(`Approval #${id} failed: ${d.error||'Error'}`);
      } else {
        Z(`Approval #${id} updated: ${d.status}`);
      }
      if (cid) {
        try {
          let latestMsgs = await req(`/conversations/${cid}/messages`);
          if (Array.isArray(latestMsgs)) {
            M(latestMsgs.map((m: any) => ({ role: m.role, content: m.content })));
          }
        } catch (err) {}
      }
      await refresh();
      if (d.tool_name && d.tool_name.startsWith('browser.')) {
        try {
          await loadBrowserData();
          await takeScreenshot();
        } catch (_) {}
      }
    } catch(e:any) {
      Z(e.message);
      await refresh();
    }
  }

  // Browser Actions
  async function navigate(target?: string) {
    let toNav = target || bUrl;
    if (!toNav.trim()) return;
    setBLoading(true);
    try {
      let res = await req('/browser/navigate', { method: 'POST', body: JSON.stringify({ url: toNav }) });
      setBUrl(res.url);
      Z(`Navigated to ${res.url}`);
      await takeScreenshot();
      await loadBrowserData();
    } catch (e: any) {
      Z(`Navigation failed: ${e.message}`);
    } finally {
      setBLoading(false);
    }
  }

  async function browserNav(action: 'back'|'forward'|'refresh') {
    setBLoading(true);
    try {
      let res = await req(`/browser/${action}`, { method: 'POST' });
      if (res && res.url) setBUrl(res.url);
      await takeScreenshot();
      await loadBrowserData();
    } catch (e: any) {
      Z(`Action ${action} failed: ${e.message}`);
    } finally {
      setBLoading(false);
    }
  }

  async function openNewTab() {
    try {
      await req('/browser/tabs/open', { method: 'POST', body: JSON.stringify({ url: null }) });
      await loadBrowserData();
    } catch (e: any) {
      Z(`Failed to open tab: ${e.message}`);
    }
  }

  async function closeTab(idx: number, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await req(`/browser/tabs/${idx}`, { method: 'DELETE' });
      await loadBrowserData();
    } catch (e: any) {
      Z(`Failed to close tab: ${e.message}`);
    }
  }

  async function switchTab(idx: number) {
    try {
      let res = await req(`/browser/tabs/${idx}/switch`, { method: 'POST' });
      setBUrl(res.url);
      await takeScreenshot();
      await loadBrowserData();
    } catch (e: any) {
      Z(`Failed to switch tab: ${e.message}`);
    }
  }

  async function takeScreenshot() {
    try {
      let ss = await req('/browser/screenshot');
      setBScreenshot(ss.base64);
    } catch (e: any) {
      // Ignored if blank page
    }
  }

  async function doWebSearch() {
    if (!bQuery.trim()) return;
    setBLoading(true);
    try {
      let res = await req('/browser/search', { method: 'POST', body: JSON.stringify({ query: bQuery, max_results: 5 }) });
      setBResults(res);
      Z(`Found ${res.length} search results`);
    } catch (e: any) {
      Z(`Web search failed: ${e.message}`);
    } finally {
      setBLoading(false);
    }
  }

  async function clearBrowserData() {
    try {
      await req('/browser/clear-data', { method: 'POST' });
      Z('Browser session profile and cookies cleared.');
      await loadBrowserData();
    } catch (e: any) {
      Z(`Clear data failed: ${e.message}`);
    }
  }

  async function addRule() {
    if (!rPattern.trim()) return;
    try {
      await req('/browser/rules', { method: 'POST', body: JSON.stringify({ rule_type: rType, pattern: rPattern }) });
      setRPattern('');
      Z('Security rule saved.');
      await loadBrowserData();
    } catch (e: any) {
      Z(`Failed to add rule: ${e.message}`);
    }
  }

  async function delRule(id: number) {
    try {
      await req(`/browser/rules/${id}`, { method: 'DELETE' });
      Z('Security rule removed.');
      await loadBrowserData();
    } catch (e: any) {
      Z(`Failed to delete rule: ${e.message}`);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="mark"><Sparkles/></div>
          <div><b>LAPTOP <em>AI</em></b><small>PERSONAL INTELLIGENCE</small></div>
        </div>
        <div className="workspace">
          <div className="avatar">A</div>
          <div><b>Personal Workspace</b><small>Local environment</small></div>
        </div>
        <div className="search">
          <Search size={14}/><span>Search navigation</span><kbd>⌘ K</kbd>
        </div>
        <div className="navlabel">WORKSPACE</div>
        {nav.slice(0,2).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}
          </button>
        ))}
        <div className="navlabel">CONTROL CENTER</div>
        {nav.slice(2,5).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}{n==='Tool Registry'&&<small className="count">{tools.length}</small>}
          </button>
        ))}
        <div className="navlabel">PREFERENCES & TOOLS</div>
        {nav.slice(5).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}
          </button>
        ))}
        <div className="sidebottom">
          <div className="runtime">
            <span>LOCAL AGENT</span><b><i/> ONLINE</b>
            <strong>Workspace ready</strong>
            <small>{tools.length} tools · {servers.length} MCP servers</small>
          </div>
          <div className="user">
            <div className="avatar">A</div>
            <div><b>Administrator</b><small>Local user</small></div>
          </div>
        </div>
      </aside>

      <main>
        <header>
          <div>Workspace <ChevronRight size={14}/><b>{page}</b></div>
          <div className="right">
            {emergency.is_stopped ? (
              <button className="emergency-active-btn" onClick={clearEmergency} title="Click to clear Emergency Stop">
                <AlertTriangle size={14} /> Resume Engine
              </button>
            ) : (
              <button className="emergency-stop-btn" onClick={() => setShowStopModal(true)} title="Global Emergency Stop">
                <StopCircle size={14} /> Emergency Stop
              </button>
            )}
            <span className="online"><i/> Local engine</span>
            <button className="ghost" onClick={refresh}><RefreshCw size={16}/></button>
            <CircleHelp size={17}/>
          </div>
        </header>

        {emergency.is_stopped && (
          <div className="emergency-banner">
            <div className="emergency-banner-content">
              <AlertTriangle size={20} color="#fca5a5" />
              <div>
                <b>GLOBAL EMERGENCY STOP ENGAGED</b>
                <small>{emergency.reason || 'All tool executions and automated background tasks are blocked.'}</small>
              </div>
            </div>
            <button className="emergency-resume-btn" onClick={clearEmergency}>
              Clear & Safe Resume
            </button>
          </div>
        )}

        {showStopModal && (
          <div className="modal-backdrop">
            <div className="modal-box">
              <div className="modal-header">
                <AlertTriangle size={22} color="#ef4444" />
                <h3>Engage Global Emergency Stop?</h3>
              </div>
              <p>This will immediately prevent all tool execution, cancel running browser actions, and pause active task plans across the system without requiring cloud connectivity.</p>
              <div className="modal-actions">
                <button className="ghost" onClick={() => setShowStopModal(false)}>Cancel</button>
                <button className="danger-btn" onClick={triggerEmergency}>Confirm Emergency Stop</button>
              </div>
            </div>
          </div>
        )}

        {notice&&<div className="notice">{notice}<button onClick={()=>Z('')}><X size={14}/></button></div>}

        <section className="content">
          {page==='Overview'&&<>
            <Heading tag="YOUR COMMAND CENTER" title="Good to see you." desc="Your personal AI workspace, connected to your machine and the tools you choose." action={<button className="primary" onClick={()=>P('Chat')}><Plus size={15}/> New conversation</button>}/>
            <div className="hero">
              <div className="hero-text">
                <span><Sparkles size={13}/> PERSONAL AI · READY</span>
                <h1>Make your computer<br/><em>work for you.</em></h1>
                <p>One intelligent workspace to think, build, automate and get things done — with you in control.</p>
                <button className="primary" onClick={()=>P('Chat')}>Start a conversation <ArrowUpRight size={15}/></button>
              </div>
              <div className="orb"><div className="core"><Sparkles size={35}/></div><i/><b/><small/></div>
              <footer><span>● Local runtime active</span><span>PRIVATE BY DESIGN</span></footer>
            </div>
            <div className="stats">
              <Stat icon={Boxes} label="Registered tools" value={tools.length} note="Native + MCP + Browser"/>
              <Stat icon={Plug} label="MCP connections" value={servers.length} note="External tool servers"/>
              <Stat icon={ShieldCheck} label="Pending approvals" value={approvals.filter((a:any)=>a.status==='pending').length} note="Awaiting review"/>
              <Stat icon={Cpu} label="Memory usage" value={system.memory_percent?system.memory_percent+'%':'—'} note={system.memory_total_gb?system.memory_total_gb+' GB installed RAM':'System telemetry'}/>
            </div>
            <div className="sectiontitle">
              <div><b>Workspace overview</b><small>Live status from your local environment</small></div>
              <span className="live">● LIVE</span>
            </div>
            <div className="lower">
              <div className="panel">
                <h3>System performance</h3>
                <small>Your machine at a glance</small>
                <Meter label="CPU utilization" val={system.cpu_percent}/>
                <Meter label="Memory utilization" val={system.memory_percent}/>
                <Meter label="Storage utilization" val={system.disk_percent}/>
              </div>
              <div className="panel">
                <h3>Quick actions</h3>
                <small>Jump into your workflow</small>
                <Quick icon={MessageSquare} title="Ask your AI" sub="Plan, reason and create" click={()=>P('Chat')}/>
                <Quick icon={Globe} title="Web & Browser" sub="Automated navigation and search" click={()=>P('Browser')}/>
                <Quick icon={Plug} title="Manage integrations" sub="Connect tools and MCP servers" click={()=>P('Tool Registry')}/>
                <Quick icon={Bot} title="Configure AI models" sub="Gemini · Groq · OpenRouter" click={()=>P('Models')}/>
              </div>
            </div>
          </>}

          {page==='Chat'&&<div className="chatpage">
            <div className="chatmain">
              <Heading tag="PERSONAL ASSISTANT" title="Chat workspace" desc="Think through problems, plan work and use your connected tools."/>
              <div className="thread">
                {msgs.length===0?<div className="welcome">
                  <div className="welcomeicon"><Sparkles/></div>
                  <h2>What can I help you with?</h2>
                  <p>Start with a question, a project, or a task you want to work through.</p>
                  <div className="prompts">
                    <button onClick={()=>Xt('Give me an overview of my system resources.')}>⌁ Check my system</button>
                    <button onClick={()=>Xt('Search the web for FastAPI latest documentation.')}>⌘ Search the web</button>
                    <button onClick={()=>Xt('Navigate to https://example.com and describe the page.')}>✧ Browse website</button>
                  </div>
                </div>:msgs.map((m,i)=>(
                  <div className="message" key={i}>
                    <div className="msgicon">{m.role==='assistant'?<Sparkles size={15}/>:'A'}</div>
                    <div><small>{m.role==='assistant'?'LAPTOP AI':'YOU'}</small><p>{m.content}</p></div>
                  </div>
                ))}
                {busy&&<div className="message"><div className="msgicon"><Sparkles size={15}/></div><div><small>LAPTOP AI</small><p className="muted">{infStatus || 'Thinking…'}</p></div></div>}
                {infStatus && !busy && <div style={{padding:'6px 12px',background:'rgba(56,189,248,0.1)',border:'1px solid rgba(56,189,248,0.3)',borderRadius:'6px',color:'#7dd3fc',fontSize:'11px',margin:'6px 0'}}><small>● {infStatus}</small></div>}
              </div>
              <div className="composer">
                <textarea value={text} onChange={e=>Xt(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}} placeholder="Message LAPTOP AI…"/>
                <div>
                  <small><ShieldCheck size={13}/> Actions require permission · Cloud inference</small>
                  <button className="send" onClick={send} disabled={busy||!text.trim()}><Send size={16}/></button>
                </div>
              </div>
              <small className="disclaimer">AI can make mistakes. Review important outputs and approve sensitive actions.</small>
            </div>
            <aside className="chatconfig">
              <div className="panel">
                <label>MODEL CONFIGURATION</label>
                <small>Provider</small>
                <select value={provider} onChange={e=>{Pr(e.target.value);Mo(e.target.value==='gemini'?'gemini-2.5-flash':e.target.value==='groq'?'openai/gpt-oss-20b':'openrouter/auto')}}>
                  <option value="gemini">Google Gemini</option>
                  <option value="groq">Groq</option>
                  <option value="openrouter">OpenRouter</option>
                </select>
                <small>Model ID</small>
                <input value={model} onChange={e=>Mo(e.target.value)}/>
                <p className="hint">API keys remain on your local backend.</p>
              </div>
              <div className="panel">
                <label>CONVERSATION INTELLIGENCE</label>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',margin:'6px 0'}}>
                  <span style={{fontSize:11,color:'#94a3b8'}}>{cid ? `Chat #${cid}` : 'New session'}</span>
                  <button className="ghost" style={{padding:'2px 7px',fontSize:10}} onClick={startNewChat}>New Chat</button>
                </div>
                <p className="hint" style={{margin:'4px 0 8px 0',fontSize:9}}>
                  Selective memories and historical decisions are injected into prompts within model token budget.
                </p>
                <button className="secondary full" style={{fontSize:11,padding:'5px 10px',display:'flex',alignItems:'center',justifyContent:'center',gap:5}} onClick={summarizeChat} disabled={!cid || busy}>
                  <Brain size={13}/> Summarize to Memory
                </button>
              </div>
              <div className="panel">
                <label>RESILIENCE & RATE LIMITS</label>
                <div style={{display:'flex',alignItems:'center',gap:'8px',margin:'8px 0'}}>
                  <input
                    type="checkbox"
                    id="chat-fallback"
                    checked={autoFallback}
                    onChange={e=>toggleAutoFallback(e.target.checked)}
                    style={{cursor:'pointer'}}
                  />
                  <label htmlFor="chat-fallback" style={{fontSize:'10px',cursor:'pointer',fontWeight:600}}>
                    Auto Fallback on 429
                  </label>
                </div>
                <small style={{display:'block',color:'#8fa8d6',fontSize:'9px'}}>
                  Fallback target: {fbProvider.toUpperCase()} ({fbModel})
                </small>
                <p className="hint" style={{marginTop:'6px',fontSize:'8px'}}>
                  Automatic token budgeting & bounded backoff protect Groq's 8,000 TPM quota.
                </p>
              </div>
              <div className="panel">
                <label>CAPABILITIES</label>
                {['Tool registry','MCP protocol','Browser automation','Web search','Permission gates','Rate limit backoff'].map(x=>(
                  <p className="cap" key={x}>● <span>{x}</span></p>
                ))}
              </div>
            </aside>
          </div>}

          {page==='Tool Registry'&&<>
            <Heading tag="EXTENSIBILITY" title="Tool registry" desc="One control plane for native Python capabilities, browser automation, and MCP integrations." action={<button className="secondary" onClick={refresh}><RefreshCw size={14}/> Refresh registry</button>}/>
            <div className="stats registry-stats">
              <Stat label="Available tools" value={tools.length}/>
              <Stat label="Native tools" value={tools.filter(t=>t.source==='native').length}/>
              <Stat label="Browser tools" value={tools.filter(t=>t.source==='browser').length}/>
              <Stat label="MCP tools" value={tools.filter(t=>t.source==='mcp').length}/>
            </div>
            <div className="lower registrylower">
              <div className="panel">
                <h3>Registered tools</h3>
                <small>Capabilities available to the agent</small>
                {tools.map(t=>(
                  <div className="tool" key={t.name}>
                    <div className="toolico">{t.source==='browser'?<Globe size={15}/>:<Terminal size={15}/>}</div>
                    <div><b>{t.name}</b><small>{t.description}</small></div>
                    <span className={'risk '+t.risk}>{t.risk}</span>
                  </div>
                ))}
              </div>
              <div className="panel">
                <h3>MCP server connections</h3>
                <small>Extend the agent with external capabilities</small>
                <div className="tabs">
                  <button className={transport==='stdio'?'on':''} onClick={()=>Tr('stdio')}>Local process</button>
                  <button className={transport==='http'?'on':''} onClick={()=>Tr('http')}>HTTP endpoint</button>
                </div>
                <label>Server name</label>
                <input value={name} onChange={e=>N(e.target.value)} placeholder="e.g. GitHub tools"/>
                {transport==='stdio'?<>
                  <label>Command</label>
                  <input value={cmd} onChange={e=>Cm(e.target.value)} placeholder="npx"/>
                  <label>Arguments · one per line</label>
                  <textarea value={args} onChange={e=>Ar(e.target.value)} placeholder="-y&#10;@modelcontextprotocol/server-filesystem&#10;C:\Users\you\Documents"/>
                </>:<>
                  <label>Streamable HTTP URL</label>
                  <input value={url} onChange={e=>U(e.target.value)} placeholder="https://server.example.com/mcp"/>
                </>}
                <button className="primary full" disabled={!name||!(transport==='stdio'?cmd:url)} onClick={add}><Plus size={14}/> Connect server</button>
                <p className="hint">Only connect MCP servers from sources you trust.</p>
                <hr/>
                <label>CONFIGURED MCP SERVERS ({servers.length})</label>
                {servers.map((s:any)=>(
                  <div className="server-card" key={s.id}>
                    <div className="server-head">
                      <div>
                        <b>{s.name}</b>
                        <small style={{display:'block',color:'#78859a',fontSize:'8px',marginTop:'2px'}}>
                          {s.transport} · {s.id} · {s.tool_count||s.tools?.length||0} tools · {s.last_connected_at?new Date(s.last_connected_at).toLocaleTimeString():'Never'}
                        </small>
                      </div>
                      <div className="server-actions">
                        <span className={'status-badge '+s.status}>{s.status}</span>
                        {s.status==='connected'?<button onClick={()=>toggleServer(s.id,false)}>Disconnect</button>:<button onClick={()=>toggleServer(s.id,true)}>Connect</button>}
                        <button className="danger" onClick={()=>removeServer(s.id)}>Remove</button>
                      </div>
                    </div>
                    {s.error&&<small style={{display:'block',color:'#f09898',fontSize:'8px',marginTop:'6px'}}>Error: {s.error}</small>}
                    {s.tools&&s.tools.length>0&&<div className="server-tools">
                      {s.tools.map((t:any)=><span className="tool-tag" key={t.name} title={t.description}>{t.name}</span>)}
                    </div>}
                  </div>
                ))}
                {!servers.length&&<p className="muted">No MCP servers configured yet.</p>}
              </div>
            </div>
          </>}

          {page==='Browser'&&<>
            <Heading tag="AUTOMATION & WEB" title="Browser workspace" desc="Playwright automation, semantic DOM inspection, downloads, and search." action={
              <button className="secondary" onClick={loadBrowserData}><RefreshCw size={14}/> Refresh browser</button>
            }/>
            <div className="stats registry-stats">
              <Stat icon={Globe} label="Browser engine" value={bStatus.is_running?'Running':'Idle'} note={bStatus.headless?'Headless Chromium':'Visible'}/>
              <Stat icon={LayersIcon} label="Active tabs" value={bTabs.length} note={`Active tab #${bStatus.active_tab_index}`}/>
              <Stat icon={Download} label="Saved downloads" value={bDownloads.length} note="Downloads/LAPTOP_AI"/>
              <Stat icon={Shield} label="Security rules" value={bRules.length} note="Domain allowlists & restrictions"/>
            </div>

            <div className="browser-layout">
              <div>
                <div className="browser-chrome">
                  <div className="browser-tabs-bar">
                    {bTabs.map((t:any)=>(
                      <div className={'browser-tab '+(t.is_active?'active':'')} key={t.index} onClick={()=>switchTab(t.index)}>
                        <Globe size={11}/>
                        <span title={t.url}>{t.title||'Tab'}</span>
                        <button onClick={(e)=>closeTab(t.index, e)}>×</button>
                      </div>
                    ))}
                    <button className="ghost" style={{padding:'4px 8px',fontSize:'11px'}} onClick={openNewTab} title="Open New Tab">+</button>
                  </div>

                  <div className="browser-nav-bar">
                    <button onClick={()=>browserNav('back')} title="Back"><ArrowLeft size={13}/></button>
                    <button onClick={()=>browserNav('forward')} title="Forward"><ArrowRight size={13}/></button>
                    <button onClick={()=>browserNav('refresh')} title="Refresh"><RotateCw size={13}/></button>
                    <input className="browser-url-input" value={bUrl} onChange={e=>setBUrl(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')navigate()}} placeholder="https://example.com"/>
                    <button className="primary" style={{width:'auto',padding:'0 12px'}} onClick={()=>navigate()} disabled={bLoading}>Go</button>
                    <button onClick={takeScreenshot} title="Capture Screenshot"><Camera size={13}/></button>
                  </div>
                </div>

                <div className="browser-preview-card">
                  <div className="browser-preview-header">
                    <span><b>VIEWPORT PREVIEW</b> {bStatus.active_title ? `· ${bStatus.active_title}` : ''}</span>
                    <button className="ghost" style={{fontSize:'8px',color:'#8fa8d6'}} onClick={takeScreenshot}><Camera size={11}/> Take screenshot</button>
                  </div>
                  <div className="browser-preview-body">
                    {bScreenshot ? (
                      <img src={bScreenshot} alt="Browser Viewport Screenshot"/>
                    ) : (
                      <div style={{textAlign:'center',color:'#55637a',padding:'40px 0'}}>
                        <Globe size={34} style={{marginBottom:'10px',opacity:0.4}}/>
                        <p style={{fontSize:'10px',margin:0}}>No screenshot captured yet. Enter a URL and press Go.</p>
                      </div>
                    )}
                  </div>
                </div>

                <div className="panel search-card">
                  <h3>Web search subsystem</h3>
                  <small>Search the web cleanly via DuckDuckGo</small>
                  <div className="search-input-group">
                    <input value={bQuery} onChange={e=>setBQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')doWebSearch()}} placeholder="Search documentation, libraries, guides…"/>
                    <button className="primary" style={{padding:'0 14px'}} onClick={doWebSearch} disabled={bLoading||!bQuery.trim()}>Search</button>
                  </div>
                  {bResults.length > 0 && <div style={{marginTop:'12px'}}>
                    {bResults.map((r:any)=>(
                      <div className="search-result-item" key={r.rank}>
                        <a href={r.url} target="_blank" rel="noreferrer" onClick={(e)=>{e.preventDefault();setBUrl(r.url);navigate(r.url);}}>
                          {r.title} <ExternalLink size={9} style={{verticalAlign:'middle'}}/>
                        </a>
                        <small>{r.url}</small>
                        <p>{r.snippet}</p>
                      </div>
                    ))}
                  </div>}
                </div>
              </div>

              <div>
                <div className="panel">
                  <h3>Browser session & profile</h3>
                  <small>Persistent user session data and storage</small>
                  <p className="hint"><ShieldCheck size={13}/> Cookies and logins persist in local user data dir.</p>
                  <code style={{fontSize:'7px',overflowWrap:'anywhere'}}>{bStatus.profile_dir || 'backend/data/browser_profile'}</code>
                  <button className="secondary full" style={{marginTop:'10px'}} onClick={clearBrowserData}><Trash2 size={13}/> Clear browsing data & cookies</button>
                </div>

                <div className="panel">
                  <h3>Domain security & allowlists</h3>
                  <small>Configure permitted and blocked domain rules</small>
                  <div style={{margin:'8px 0'}}>
                    {bRules.map((rl:any)=>(
                      <span key={rl.id} className={'rule-tag '+(rl.rule_type==='blocklist_domain'?'blocklist':'')}>
                        {rl.rule_type==='allowlist_domain'?'✓ ':'✕ '}{rl.pattern}
                        <button onClick={()=>delRule(rl.id)}>×</button>
                      </span>
                    ))}
                    {!bRules.length && <p className="muted" style={{fontSize:'8px'}}>No custom domain rules configured (standard private IP / SSRF barriers active).</p>}
                  </div>
                  <hr/>
                  <label>Add new domain rule</label>
                  <div style={{display:'flex',gap:'6px',marginTop:'4px'}}>
                    <select style={{width:'40%'}} value={rType} onChange={e=>setRType(e.target.value)}>
                      <option value="allowlist_domain">Allowlist</option>
                      <option value="blocklist_domain">Blocklist</option>
                    </select>
                    <input style={{flex:1,marginTop:0}} value={rPattern} onChange={e=>setRPattern(e.target.value)} placeholder="wikipedia.org"/>
                  </div>
                  <button className="secondary full" style={{marginTop:'8px'}} onClick={addRule} disabled={!rPattern.trim()}><Plus size={12}/> Add security rule</button>
                </div>

                <div className="panel">
                  <h3>Download history ({bDownloads.length})</h3>
                  <small>Files saved to Downloads/LAPTOP_AI</small>
                  {bDownloads.map((d:any)=>(
                    <div className="download-item" key={d.id}>
                      <div>
                        <b>{d.filename}</b>
                        <small>{(d.size_bytes/1024).toFixed(1)} KB · {d.downloaded_at ? new Date(d.downloaded_at).toLocaleTimeString() : ''}</small>
                        <small style={{color:'#5d6f88',overflowWrap:'anywhere'}}>{d.url}</small>
                      </div>
                      <span className="tool-tag" style={{background:'#192231'}}>Saved</span>
                    </div>
                  ))}
                  {!bDownloads.length && <p className="muted" style={{fontSize:'8px'}}>No downloads recorded yet.</p>}
                </div>
              </div>
            </div>
          </>}

          {(page==='Models'||page==='Settings')&&<>
            <Heading tag="AI CONFIGURATION" title="Models & providers" desc="Configure cloud inference. Credentials are saved by the local backend."/>
            <div className="providers">
              {['gemini','groq','openrouter'].map(x=>(
                <div className="panel" key={x}>
                  <div className="providerline">
                    <div className={'providerlogo '+x}>{x==='gemini'?'✦':x==='groq'?'G':'◈'}</div>
                    <span>{providers[x]?.configured?'● CONFIGURED':'○ NOT CONNECTED'}</span>
                  </div>
                  <h3>{x==='gemini'?'Google Gemini':x==='groq'?'Groq':'OpenRouter'}</h3>
                  <small>{x==='gemini'?'Generative models API':x==='groq'?'GroqCloud inference':'Multi-model gateway'}</small>
                  <code>{x==='gemini'?'gemini-2.5-flash':x==='groq'?'openai/gpt-oss-20b':'openrouter/auto'}</code>
                  <button className="secondary full" onClick={()=>Kp(x)}>Configure provider</button>
                </div>
              ))}
            </div>
            <div className="panel keypanel">
              <h3>API credentials</h3>
              <small>Keys are stored in backend/.env. Restart backend after saving.</small>
              <div className="keyform">
                <div>
                  <label>Provider</label>
                  <select value={kp} onChange={e=>Kp(e.target.value)}>
                    <option value="gemini">Gemini</option>
                    <option value="groq">Groq</option>
                    <option value="openrouter">OpenRouter</option>
                  </select>
                </div>
                <div>
                  <label>API key</label>
                  <input type="password" value={key} onChange={e=>K(e.target.value)} placeholder="Paste provider key locally"/>
                </div>
                <button className="primary" disabled={!key} onClick={save}>Save key <Check size={14}/></button>
              </div>
              <p className="hint"><ShieldCheck size={13}/> Never paste API keys into chat.</p>
            </div>

            <div className="panel" style={{marginTop:'16px'}}>
              <h3>Rate limit management & intelligent fallback</h3>
              <small>Protect against provider quotas (e.g. Groq 8,000 TPM limit)</small>
              <div style={{display:'flex',alignItems:'center',gap:'12px',marginTop:'12px'}}>
                <input
                  type="checkbox"
                  id="auto-fallback-toggle"
                  checked={autoFallback}
                  onChange={e=>toggleAutoFallback(e.target.checked)}
                  style={{width:'16px',height:'16px',cursor:'pointer'}}
                />
                <label htmlFor="auto-fallback-toggle" style={{cursor:'pointer',fontSize:'11px',fontWeight:600}}>
                  Enable Auto Provider Fallback on Rate Limit (HTTP 429)
                </label>
              </div>
              <div style={{marginTop:'10px',display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px'}}>
                <div>
                  <small style={{fontSize:'10px',color:'#8fa8d6'}}>Fallback Provider</small>
                  <select
                    value={fbProvider}
                    onChange={e=>{
                      let p = e.target.value;
                      setFbProvider(p);
                      let m = p==='gemini'?'gemini-2.5-flash':p==='groq'?'openai/gpt-oss-20b':'openrouter/auto';
                      setFbModel(m);
                      req('/settings', {method:'POST', body:JSON.stringify({auto_provider_fallback:autoFallback, fallback_provider:p, fallback_model:m})});
                    }}
                    style={{marginTop:'4px'}}
                  >
                    <option value="gemini">Google Gemini (Recommended - 1M TPM)</option>
                    <option value="openrouter">OpenRouter</option>
                  </select>
                </div>
                <div>
                  <small style={{fontSize:'10px',color:'#8fa8d6'}}>Fallback Model</small>
                  <input
                    value={fbModel}
                    onChange={e=>{
                      setFbModel(e.target.value);
                      req('/settings', {method:'POST', body:JSON.stringify({auto_provider_fallback:autoFallback, fallback_provider:fbProvider, fallback_model:e.target.value})});
                    }}
                    style={{marginTop:'4px'}}
                  />
                </div>
              </div>
              <p className="hint" style={{marginTop:'10px'}}>
                When enabled, if Groq encounters a 429 rate limit that exceeds retries, LAPTOP AI will seamlessly continue the turn using <strong>{fbProvider.toUpperCase()}</strong> ({fbModel}) without losing context or repeating completed actions.
              </p>
            </div>
          </>}

          {page==='Activity Log'&&<>
            <Heading tag="OBSERVABILITY" title="Activity & approvals" desc="Review tool activity and sensitive actions awaiting approval."/>
            <div className="panel">
              <h3>Pending approvals ({approvals.filter((a:any)=>a.status==='pending').length})</h3>
              {approvals.filter((a:any)=>a.status==='pending').map((a:any)=>(
                <div className="approval" key={a.id}>
                  <div>
                    <div className="approval-meta">
                      <b>{a.tool_name}</b>
                      <span className="risk approval">#{a.id}</span>
                      {a.expires_at&&<small className="muted">Expires: {new Date(a.expires_at).toLocaleTimeString()}</small>}
                    </div>
                    <small>{a.args}</small>
                  </div>
                  <button onClick={()=>decide(a.id,false)}>Reject</button>
                  <button className="approve" onClick={()=>decide(a.id,true)}>Approve</button>
                </div>
              ))}
              {!approvals.filter((a:any)=>a.status==='pending').length&&<p className="muted">No pending approvals awaiting review.</p>}
            </div>

            <div className="panel">
              <h3>Approval lifecycle & history</h3>
              {approvals.filter((a:any)=>a.status!=='pending').map((a:any)=>(
                <div className="approval" key={a.id}>
                  <div>
                    <div className="approval-meta">
                      <b>{a.tool_name}</b>
                      <span className={'status-badge '+a.status}>{a.status}</span>
                      <small className="muted">#{a.id} · {a.decision_by||'user'} · {a.executed_at||a.decision_at||a.created_at}</small>
                    </div>
                    <small>{a.args}</small>
                    {a.result&&<div className="approval-res"><strong>Result:</strong> {a.result}</div>}
                    {a.error&&<div className="approval-res" style={{color:'#f09898'}}><strong>Error:</strong> {a.error}</div>}
                  </div>
                </div>
              ))}
              {!approvals.filter((a:any)=>a.status!=='pending').length&&<p className="muted">No historical approval records.</p>}
            </div>

            <div className="panel audit">
              <h3>Recent activity</h3>
              {audit.map((a:any)=>(
                <div className="tool" key={a.id}>
                  <div className="toolico"><Clock3 size={14}/></div>
                  <div><b>{a.event}</b><small>{a.detail} · {a.created_at}</small></div>
                </div>
              ))}
            </div>
          </>}

          {page==='Tasks'&&<>
            <Heading
              tag="AUTONOMOUS TASK MANAGEMENT"
              title="Intelligent Tasks & Scheduler"
              desc="Structured multi-step planning, dependency execution, checkpoints and persistent automation."
              action={
                <div style={{display:'flex',gap:8}}>
                  <button className={tasksTab==='plans'?'primary':'ghost'} onClick={()=>setTasksTab('plans')}><Workflow size={15}/> Task Planner</button>
                  <button className={tasksTab==='schedules'?'primary':'ghost'} onClick={()=>setTasksTab('schedules')}><Calendar size={15}/> Scheduler</button>
                </div>
              }
            />

            <div className="phase-tabs">
              <button className={'phase-tab-btn '+(tasksTab==='plans'?'active':'')} onClick={()=>setTasksTab('plans')}>
                <Workflow size={14}/> Executable Plans ({tasksList.length})
              </button>
              <button className={'phase-tab-btn '+(tasksTab==='schedules'?'active':'')} onClick={()=>setTasksTab('schedules')}>
                <Calendar size={14}/> Scheduled Automation ({schedulesList.length})
              </button>
            </div>

            {tasksTab==='plans'&&(
              <>
                <div className="planner-form">
                  <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:8}}>
                    <Brain size={16} color="#60a5fa"/>
                    <b style={{fontSize:13,color:'#f1f5f9'}}>Generate Executable Plan</b>
                  </div>
                  <p style={{fontSize:11,color:'#94a3b8',margin:'0 0 10px'}}>Convert any complex or consequential request into structured, dependency-checked execution steps.</p>
                  <div className="planner-input-row">
                    <input
                      style={{flex:1,background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'8px 12px',color:'#fff',fontSize:12}}
                      placeholder="e.g. Audit system health, inspect high-CPU processes, and capture a screenshot..."
                      value={newPlanPrompt}
                      onChange={e=>setNewPlanPrompt(e.target.value)}
                      onKeyDown={e=>{if(e.key==='Enter') createPlan();}}
                    />
                    <button className="primary" onClick={createPlan} disabled={isPlanning||!newPlanPrompt.trim()}>
                      {isPlanning ? <RefreshCw size={14} className="spin"/> : <Sparkles size={14}/>} Create Plan
                    </button>
                  </div>
                </div>

                <div className="task-list">
                  {tasksList.map(t=>(
                    <div className="task-card" key={t.id}>
                      <div className="task-header">
                        <div>
                          <h3>{t.title}</h3>
                          <p>{t.objective} · Created {t.created_at}</p>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:6,flexWrap:'wrap'}}>
                          <span className={'status-pill '+t.status}>{t.status.replace('_',' ')}</span>
                          <span className={'risk '+(t.risk_level==='consequential'?'approval':'read')} style={{fontSize:9,padding:'2px 6px'}}>
                            {t.risk_level}
                          </span>
                          {t.approval_required ? (
                            <span style={{fontSize:9,color:'#fbbf24',background:'rgba(251,191,36,0.1)',border:'1px solid rgba(251,191,36,0.3)',borderRadius:4,padding:'2px 6px',display:'flex',alignItems:'center',gap:3}}>
                              <ShieldCheck size={10}/> Approval Required
                            </span>
                          ) : null}
                          <span style={{fontSize:10,color:'#94a3b8',background:'#1a2233',padding:'3px 8px',borderRadius:4}}>
                            {t.completed_steps}/{t.total_steps} steps
                          </span>
                        </div>
                      </div>

                      {t.error&&<div style={{background:'#2d1519',border:'1px solid #7f1d1d',color:'#fca5a5',padding:'8px 12px',borderRadius:6,fontSize:11,marginBottom:10}}>
                        <strong>Notice:</strong> {t.error}
                      </div>}

                      {t.result&&<div style={{background:'#132b20',border:'1px solid #065f46',color:'#6ee7b7',padding:'8px 12px',borderRadius:6,fontSize:11,marginBottom:10}}>
                        <strong>Result:</strong> {t.result}
                      </div>}

                      <div className="step-timeline">
                        {(t.steps||[]).map((s:any)=>(
                          <div className="step-row" key={s.id} style={{flexDirection:'column',alignItems:'stretch',gap:4}}>
                            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                              <div className="step-info">
                                <span className="step-num">{s.step_index}</span>
                                <div>
                                  <b style={{color:'#f1f5f9'}}>{s.title}</b>
                                  <small style={{display:'block',color:'#64748b'}}>
                                    Tool: <code>{s.tool_name}</code>
                                    {s.dependencies?.length ? ` · Depends on Step ${s.dependencies.join(', ')}` : ''}
                                    {s.started_at ? ` · ${new Date(s.started_at).toLocaleTimeString()}` : ''}
                                  </small>
                                </div>
                              </div>
                              <div style={{display:'flex',alignItems:'center',gap:6}}>
                                <span className={'status-pill '+s.status}>{s.status.replace('_',' ')}</span>
                                {s.status==='failed'&&(
                                  <div style={{display:'flex',alignItems:'center',gap:4}}>
                                    {(s.checkpoint_data?.includes('manual_review') || s.error?.includes('manual review'))&&(
                                      <>
                                        <button className="ghost" style={{padding:'2px 6px',fontSize:10,color:'#34d399',borderColor:'#059669'}} onClick={()=>recoverTaskStep(t.id, s.id, 'resolve')} title="Mark as resolved manually after verifying outcome">
                                          <Check size={11}/> Resolve
                                        </button>
                                        <button className="ghost" style={{padding:'2px 6px',fontSize:10,color:'#94a3b8'}} onClick={()=>recoverTaskStep(t.id, s.id, 'skip')} title="Skip this step and continue dependent steps">
                                          Skip
                                        </button>
                                      </>
                                    )}
                                    <button className="ghost" style={{padding:'2px 6px',fontSize:10}} onClick={()=>retryTaskStep(t.id, s.id)} title="Retry step">
                                      <RotateCw size={11}/> Retry
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                            {s.error&&(
                              <div style={{background:'#2d1519',border:'1px solid #7f1d1d',color:'#fca5a5',padding:'4px 8px',borderRadius:4,fontSize:10,marginLeft:28}}>
                                <strong>Error:</strong> {s.error}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      <div className="task-controls">
                        {['planned','paused','draft'].includes(t.status)&&(
                          <button className="primary" onClick={()=>executePlan(t.id)}><Play size={13}/> Execute Plan</button>
                        )}
                        {t.status==='running'&&(
                          <button className="ghost" onClick={()=>pauseTask(t.id)}><Pause size={13}/> Pause</button>
                        )}
                        {['paused','failed'].includes(t.status)&&(
                          <button className="ghost" onClick={()=>resumeTask(t.id)}><Play size={13}/> Resume</button>
                        )}
                        {!['completed','cancelled'].includes(t.status)&&(
                          <button className="ghost" style={{color:'#f87171'}} onClick={()=>cancelTask(t.id)}><X size={13}/> Cancel Plan</button>
                        )}
                      </div>
                    </div>
                  ))}
                  {!tasksList.length&&<p className="muted">No task plans created yet. Use the prompt above to generate your first plan.</p>}
                </div>
              </>
            )}

            {tasksTab==='schedules'&&(
              <>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14}}>
                  <p style={{fontSize:12,color:'#94a3b8',margin:0}}>Automated tasks run periodically in the background and survive restarts.</p>
                  <button className="primary" onClick={()=>setShowAddSched(true)}><Plus size={14}/> Add Scheduled Task</button>
                </div>

                {showAddSched&&(
                  <div className="planner-form" style={{marginBottom:16}}>
                    <div style={{display:'flex',justifyContent:'space-between',marginBottom:10}}>
                      <b style={{fontSize:13,color:'#fff'}}>New Scheduled Task</b>
                      <button className="icon-btn" onClick={()=>setShowAddSched(false)}><X size={14}/></button>
                    </div>
                    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
                      <div>
                        <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>TASK NAME</label>
                        <input
                          style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                          placeholder="e.g. Daily Health Check"
                          value={schedName}
                          onChange={e=>setSchedName(e.target.value)}
                        />
                      </div>
                      <div>
                        <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>RECURRENCE</label>
                        <select
                          style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                          value={schedType}
                          onChange={e=>setSchedType(e.target.value)}
                        >
                          <option value="once">Once</option>
                          <option value="daily">Daily</option>
                          <option value="weekly">Weekly</option>
                          <option value="interval">Custom Interval</option>
                        </select>
                      </div>
                    </div>
                    {schedType==='interval'&&(
                      <div style={{marginBottom:10}}>
                        <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>INTERVAL (SECONDS)</label>
                        <input
                          type="number"
                          style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                          value={schedInterval}
                          onChange={e=>setSchedInterval(Number(e.target.value))}
                        />
                      </div>
                    )}
                    <div style={{marginBottom:10}}>
                      <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>USER INSTRUCTION</label>
                      <input
                        style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                        placeholder="e.g. Inspect system telemetry and report CPU/RAM..."
                        value={schedPrompt}
                        onChange={e=>setSchedPrompt(e.target.value)}
                      />
                    </div>
                    <div style={{display:'flex',justifyContent:'flex-end',gap:8}}>
                      <button className="ghost" onClick={()=>setShowAddSched(false)}>Cancel</button>
                      <button className="primary" onClick={saveSchedule} disabled={!schedName.trim()||!schedPrompt.trim()}>Create Schedule</button>
                    </div>
                  </div>
                )}

                <div className="task-list">
                  {schedulesList.map(s=>(
                    <div className="sched-card" key={s.id}>
                      <div className="sched-info">
                        <div style={{display:'flex',alignItems:'center',gap:8}}>
                          <b>{s.task_name}</b>
                          <span style={{fontSize:9,textTransform:'uppercase',background:'#1e293b',color:'#93c5fd',padding:'2px 6px',borderRadius:4,fontWeight:700}}>
                            {s.schedule_type}
                          </span>
                          <span className={'status-pill '+(s.enabled?'completed':'paused')}>
                            {s.enabled ? 'Active' : 'Disabled'}
                          </span>
                        </div>
                        <small>{s.user_request}</small>
                        <small style={{color:'#64748b'}}>Next run: {s.next_run_at} {s.last_run_at ? ` · Last run: ${s.last_run_at} (${s.last_status||'ok'})` : ''}</small>
                      </div>
                      <div style={{display:'flex',alignItems:'center',gap:8}}>
                        <button
                          className="ghost"
                          style={{fontSize:11}}
                          onClick={()=>toggleScheduleHistory(s.id)}
                        >
                          <Clock3 size={12}/> History
                        </button>
                        <button
                          className="ghost"
                          style={{fontSize:11,color:s.enabled?'#fbbf24':'#34d399'}}
                          onClick={()=>toggleSched(s.id, Boolean(s.enabled))}
                        >
                          {s.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button className="icon-btn delete" onClick={()=>deleteSched(s.id)} title="Delete schedule">
                          <Trash2 size={15}/>
                        </button>
                      </div>
                      {openHistoryId === s.id && (
                        <div style={{gridColumn:'1/-1',marginTop:8,padding:'8px 12px',background:'#0a0e17',borderRadius:6,border:'1px solid #1a2233'}}>
                          <small style={{fontWeight:700,color:'#94a3b8',display:'block',marginBottom:4}}>EXECUTION RUN HISTORY</small>
                          {(schedRuns[s.id]||[]).map((r:any)=>(
                            <div key={r.id} style={{display:'flex',justifyContent:'space-between',fontSize:10,padding:'3px 0',borderBottom:'1px solid #111827'}}>
                              <span style={{color:'#cbd5e1'}}>{new Date(r.triggered_at).toLocaleString()}</span>
                              <span className={'status-pill '+r.status} style={{fontSize:9,padding:'1px 5px'}}>{r.status}</span>
                            </div>
                          ))}
                          {!(schedRuns[s.id]||[]).length && <small className="muted">No execution runs recorded yet.</small>}
                        </div>
                      )}
                    </div>
                  ))}
                  {!schedulesList.length&&<p className="muted">No scheduled tasks configured. Click 'Add Scheduled Task' to create automated jobs.</p>}
                </div>
              </>
            )}
          </>}

          {page==='Memory'&&<>
            <Heading
              tag="PERSISTENT KNOWLEDGE ENGINE"
              title="Persistent Memory Subsystem"
              desc="Verified facts, user preferences, project summaries and workflows persisted in SQLite with FTS5 search."
              action={<button className="primary" onClick={()=>setShowAddMem(true)}><Plus size={15}/> Add Memory</button>}
            />

            <div className="memory-controls">
              <div style={{position:'relative'}}>
                <Search size={14} style={{position:'absolute',left:10,top:10,color:'#64748b'}}/>
                <input
                  style={{width:'100%',background:'#0e1422',border:'1px solid #1f293d',borderRadius:6,padding:'8px 10px 8px 32px',color:'#fff',fontSize:12}}
                  placeholder="Search memories via SQLite FTS5..."
                  value={memSearch}
                  onChange={e=>setMemSearch(e.target.value)}
                />
              </div>
              <button className="ghost" onClick={loadMemories}><RefreshCw size={14}/> Refresh</button>
            </div>

            <div className="category-chips">
              {[
                ['all', 'All Categories'],
                ['user_preference', 'Preferences'],
                ['personal_fact', 'Personal Facts'],
                ['active_project', 'Active Projects'],
                ['project_decision', 'Decisions'],
                ['conversation_summary', 'Summaries'],
                ['frequently_used_workflow', 'Workflows'],
                ['user_approved_instruction', 'Instructions'],
              ].map(([k, label])=>(
                <button
                  key={k}
                  className={'chip '+(memCat===k?'active':'')}
                  onClick={()=>setMemCat(k)}
                >
                  {label}
                </button>
              ))}
            </div>

            {showAddMem&&(
              <div className="planner-form" style={{marginBottom:18}}>
                <div style={{display:'flex',justifyContent:'space-between',marginBottom:10}}>
                  <b style={{fontSize:13,color:'#fff'}}>Store Explicit Memory</b>
                  <button className="icon-btn" onClick={()=>setShowAddMem(false)}><X size={14}/></button>
                </div>
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10,marginBottom:10}}>
                  <div>
                    <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>CATEGORY</label>
                    <select
                      style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                      value={newMemCat}
                      onChange={e=>setNewMemCat(e.target.value)}
                    >
                      <option value="user_preference">User Preference</option>
                      <option value="personal_fact">Personal Fact</option>
                      <option value="active_project">Active Project</option>
                      <option value="project_decision">Project Decision</option>
                      <option value="conversation_summary">Conversation Summary</option>
                      <option value="frequently_used_workflow">Frequently Used Workflow</option>
                      <option value="user_approved_instruction">User-Approved Instruction</option>
                    </select>
                  </div>
                  <div>
                    <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>OPTIONAL KEY / IDENTIFIER</label>
                    <input
                      style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'7px 10px',color:'#fff',fontSize:12}}
                      placeholder="e.g. python_style"
                      value={newMemKey}
                      onChange={e=>setNewMemKey(e.target.value)}
                    />
                  </div>
                </div>
                <div style={{marginBottom:10}}>
                  <label style={{fontSize:10,color:'#94a3b8',display:'block',marginBottom:4}}>CONTENT</label>
                  <textarea
                    style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:6,padding:'8px 10px',color:'#fff',fontSize:12,minHeight:70}}
                    placeholder="Enter verified fact or preference (API keys and credentials are automatically rejected)..."
                    value={newMemContent}
                    onChange={e=>setNewMemContent(e.target.value)}
                  />
                </div>
                <div style={{display:'flex',justifyContent:'flex-end',gap:8}}>
                  <button className="ghost" onClick={()=>setShowAddMem(false)}>Cancel</button>
                  <button className="primary" onClick={saveMemory} disabled={!newMemContent.trim()}>Save to Memory</button>
                </div>
              </div>
            )}

            <div className="memory-grid">
              {memories.map(m=>(
                <div className="memory-card" key={m.id}>
                  {editingMemId === m.id ? (
                    <div style={{padding:'4px 0'}}>
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
                        <b style={{fontSize:11,color:'#fff'}}>Edit Memory #{m.id}</b>
                        <button className="icon-btn" onClick={()=>setEditingMemId(null)}><X size={12}/></button>
                      </div>
                      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6,marginBottom:6}}>
                        <select
                          style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:4,padding:'4px 6px',color:'#fff',fontSize:11}}
                          value={editMemCat}
                          onChange={e=>setEditMemCat(e.target.value)}
                        >
                          <option value="user_preference">User Preference</option>
                          <option value="personal_fact">Personal Fact</option>
                          <option value="active_project">Active Project</option>
                          <option value="project_decision">Project Decision</option>
                          <option value="conversation_summary">Conversation Summary</option>
                          <option value="frequently_used_workflow">Workflow</option>
                          <option value="user_approved_instruction">Instruction</option>
                        </select>
                        <input
                          style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:4,padding:'4px 6px',color:'#fff',fontSize:11}}
                          placeholder="Key / Identifier"
                          value={editMemKey}
                          onChange={e=>setEditMemKey(e.target.value)}
                        />
                      </div>
                      <textarea
                        style={{width:'100%',background:'#141b2b',border:'1px solid #232d42',borderRadius:4,padding:'6px 8px',color:'#fff',fontSize:11,minHeight:60,marginBottom:6}}
                        value={editMemContent}
                        onChange={e=>setEditMemContent(e.target.value)}
                      />
                      <div style={{display:'flex',justifyContent:'flex-end',gap:6}}>
                        <button className="ghost" style={{padding:'3px 8px',fontSize:11}} onClick={()=>setEditingMemId(null)}>Cancel</button>
                        <button className="primary" style={{padding:'3px 8px',fontSize:11}} onClick={updateMemory} disabled={!editMemContent.trim()}>Save Changes</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div>
                        <div className="memory-card-header">
                          <span className="memory-cat-badge">{m.category.replace('_',' ')}</span>
                          <small style={{color:'#64748b',fontSize:10}}>#{m.id} · {Math.round(m.confidence*100)}% conf</small>
                        </div>
                        {m.key&&<div style={{fontSize:11,fontWeight:700,color:'#93c5fd',marginBottom:4}}><code>{m.key}</code></div>}
                        <div className="memory-card-body">{m.content}</div>
                      </div>
                      <div className="memory-card-footer">
                        <div>
                          <span>Source: <b>{m.source}</b></span>
                          <small style={{display:'block',color:'#475569'}}>Accessed {m.access_count}x · {m.last_accessed_at}</small>
                        </div>
                        <div className="memory-actions">
                          <button className="icon-btn" onClick={()=>startEditMem(m)} title="Edit memory"><Edit2 size={14}/></button>
                          <button className="icon-btn" onClick={()=>archiveMem(m.id)} title="Archive memory"><Archive size={14}/></button>
                          <button className="icon-btn delete" onClick={()=>deleteMem(m.id)} title="Delete permanently"><Trash2 size={14}/></button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {!memories.length&&<p className="muted" style={{gridColumn:'1/-1'}}>No persistent memories found matching filter.</p>}
            </div>
          </>}

          {!['Overview','Chat','Tool Registry','Models','Settings','Activity Log','Browser','Tasks','Memory'].includes(page)&&(
            <div className="coming">
              <Sparkles/>
              <h1>{page}</h1>
              <p>This module is reserved for the next development increment.</p>
              <span>PLANNED MODULE</span>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function Heading(p:any) {
  return <div className="heading"><div><label>{p.tag}</label><h1>{p.title}</h1><p>{p.desc}</p></div>{p.action}</div>;
}

function Stat(p:any) {
  let I = p.icon;
  return <div className="stat"><div className="staticon">{I&&<I size={16}/>}</div><small>{p.label}</small><b>{p.value}</b><em>{p.note}</em></div>;
}

function Meter({label,val}:any) {
  return <div className="meter"><div><span>{label}</span><b>{val===undefined?'—':val+'%'}</b></div><i><span style={{width:`${Math.min(100,val||0)}%`}}/></i></div>;
}

function Quick(p:any) {
  let I = p.icon;
  return <button className="quick" onClick={p.click}><I size={17}/><div><b>{p.title}</b><small>{p.sub}</small></div><ChevronRight size={15}/></button>;
}

function LayersIcon(p:any) {
  return <Globe {...p}/>;
}
