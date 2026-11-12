import {useEffect,useState} from 'react';
import {
  Activity,Bot,Boxes,ChevronRight,CircleHelp,Command,Cpu,Folder,Globe,LayoutDashboard,
  MessageSquare,Plus,Search,Send,Settings,ShieldCheck,Sparkles,Terminal,Workflow,Plug,
  RefreshCw,Check,X,Server,PanelLeftClose,Zap,Clock3,ArrowUpRight,ArrowLeft,ArrowRight,
  RotateCw,Camera,Download,ExternalLink,Trash2,Shield,Eye,Bell,User,
  AlertTriangle,Play,Pause,Calendar,Brain,Edit2,Archive,Repeat,StopCircle,
  Monitor,MousePointer,Keyboard,FileText,Table,Filter,Copy,FileCheck,Files,Lock
} from 'lucide-react';

const API = 'http://127.0.0.1:8000/api';
type Tool = {name:string;description:string;source:string;risk:string};
type Msg = {role:string;content:string};

const nav = [
  ['Overview',LayoutDashboard],
  ['Assistant',Sparkles],
  ['Chat',MessageSquare],
  ['Desktop',Monitor],
  ['Visual AI',Eye],
  ['Files',Folder],
  ['Tasks',Workflow],
  ['Memory',Brain],
  ['Browser',Globe],
  ['Tool Registry',Boxes],
  ['Models',Bot],
  ['Activity Log',Clock3],
  ['Settings',Settings],
  ['System',Activity],
  ['Terminal',Terminal]
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

  // Desktop Control State
  const [dStatus, setDStatus] = useState<any>({ available: true, display: { width: 1366, height: 768 } });
  const [dWindows, setDWindows] = useState<any[]>([]);
  const [dWindowFilter, setDWindowFilter] = useState('');
  const [dScreenshots, setDScreenshots] = useState<any[]>([]);
  const [dCurrentScreenshot, setDCurrentScreenshot] = useState<string>('');
  const [dInspection, setDInspection] = useState<any>(null);
  const [dHistory, setDHistory] = useState<any[]>([]);
  const [dTypeText, setDTypeText] = useState('');
  const [dLoading, setDLoading] = useState(false);

  // Visual Desktop Intelligence State (Queue 2)
  const [vLoading, setVLoading] = useState(false);
  const [vTarget, setVTarget] = useState<'desktop' | 'window'>('desktop');
  const [vAnalysis, setVAnalysis] = useState<any>(null);
  const [vOcr, setVOcr] = useState<any>(null);
  const [vGroundingQuery, setVGroundingQuery] = useState('');
  const [vGrounding, setVGrounding] = useState<any>(null);
  const [vComparison, setVComparison] = useState<any>(null);
  const [vHistory, setVHistory] = useState<any[]>([]);
  const [vActiveTab, setVActiveTab] = useState<'analysis' | 'elements' | 'ocr' | 'compare' | 'history'>('analysis');
  const [vSelectedElement, setVSelectedElement] = useState<any>(null);
  const [vScreenshotThumb, setVScreenshotThumb] = useState<string>('');
  const [vCompareBase, setVCompareBase] = useState<string>('');
  const [vCompareTarget, setVCompareTarget] = useState<string>('');
  const [vElementFilter, setVElementFilter] = useState<string>('all');

  // Advanced File Intelligence State (Queue 3)
  const [fTab, setFTab] = useState<'search' | 'document' | 'spreadsheet' | 'compare' | 'organize' | 'index'>('search');
  const [fSearchQuery, setFSearchQuery] = useState('');
  const [fSearchFormat, setFSearchFormat] = useState('all');
  const [fSearchResults, setFSearchResults] = useState<any[]>([]);
  const [fSearchLoading, setFSearchLoading] = useState(false);
  const [fDocPath, setFDocPath] = useState('');
  const [fDocParsed, setFDocParsed] = useState<any>(null);
  const [fDocSummary, setFDocSummary] = useState<any>(null);
  const [fDocQuestion, setFDocQuestion] = useState('');
  const [fDocAnswer, setFDocAnswer] = useState<any>(null);
  const [fDocLoading, setFDocLoading] = useState(false);
  const [fSsPath, setFSsPath] = useState('');
  const [fSsProfile, setFSsProfile] = useState<any>(null);
  const [fSsActiveSheet, setFSsActiveSheet] = useState('');
  const [fSsFilterCol, setFSsFilterCol] = useState('');
  const [fSsFilterVal, setFSsFilterVal] = useState('');
  const [fSsSortBy, setFSsSortBy] = useState('');
  const [fSsLoading, setFSsLoading] = useState(false);
  const [fCmpFileA, setFCmpFileA] = useState('');
  const [fCmpFileB, setFCmpFileB] = useState('');
  const [fCmpResult, setFCmpResult] = useState<any>(null);
  const [fCmpLoading, setFCmpLoading] = useState(false);
  const [fOrgFolder, setFOrgFolder] = useState('Downloads');
  const [fOrgDuplicates, setFOrgDuplicates] = useState<any[]>([]);
  const [fOrgPreview, setFOrgPreview] = useState<any>(null);
  const [fOrgLoading, setFOrgLoading] = useState(false);
  const [fIdxStatus, setFIdxStatus] = useState<any>(null);
  const [fIdxFolder, setFIdxFolder] = useState('Downloads');
  const [fIdxLoading, setFIdxLoading] = useState(false);

  // Proactive Personal Assistance State (Queue 4)
  const [asTab, setAsTab] = useState<'briefing' | 'reminders' | 'monitors' | 'profile' | 'notifications' | 'plan'>('briefing');
  const [asBriefing, setAsBriefing] = useState<any>(null);
  const [asBriefingLoading, setAsBriefingLoading] = useState(false);
  const [asReminders, setAsReminders] = useState<any[]>([]);
  const [asMonitors, setAsMonitors] = useState<any[]>([]);
  const [asNotifications, setAsNotifications] = useState<any[]>([]);
  const [asProfile, setAsProfile] = useState<any>(null);
  const [asDailyPlan, setAsDailyPlan] = useState<any>(null);
  const [asUnreadCount, setAsUnreadCount] = useState<number>(0);

  // Assistant forms
  const [remTitle, setRemTitle] = useState('');
  const [remDueAt, setRemDueAt] = useState('');
  const [remType, setRemType] = useState('one_time');
  const [monName, setMonName] = useState('');
  const [monType, setMonType] = useState('task_overdue');
  const [monTarget, setMonTarget] = useState('*');
  const [monThreshold, setMonThreshold] = useState(3600);
  const [natTaskInput, setNatTaskInput] = useState('');
  const [natTaskPriority, setNatTaskPriority] = useState('');
  const [newPrefKey, setNewPrefKey] = useState('');
  const [newPrefVal, setNewPrefVal] = useState('');
  const [newPrefCat, setNewPrefCat] = useState('preferences');

  let [localSessionToken, setLocalSessionToken] = useState<string>(() => {
    try {
      return sessionStorage.getItem('laptop_ai_session_token') || '';
    } catch {
      return '';
    }
  });
  let [bootstrapRequired, setBootstrapRequired] = useState<boolean>(false);
  let [manualBootstrapKey, setManualBootstrapKey] = useState<string>('');
  let [authError, setAuthError] = useState<string>('');

  async function authorizeWithKey(keyToTry?: string): Promise<string> {
    setAuthError('');
    let bToken = (keyToTry !== undefined ? keyToTry : manualBootstrapKey || '').trim();
    if (!bToken) {
      try {
        bToken = sessionStorage.getItem('laptop_ai_bootstrap_token') || '';
      } catch {}
    }
    if (!bToken) {
      setBootstrapRequired(true);
      return '';
    }
    try {
      let r = await fetch(API + '/auth/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bootstrap_token: bToken }),
      });
      if (r.ok) {
        let d = await r.json();
        let tok = d.session_token || '';
        setLocalSessionToken(tok);
        setBootstrapRequired(false);
        try {
          sessionStorage.setItem('laptop_ai_session_token', tok);
          sessionStorage.setItem('laptop_ai_bootstrap_token', bToken);
        } catch {}
        return tok;
      } else {
        let errData = await r.json().catch(() => ({}));
        let msg = errData.detail || 'Authorization failed: Invalid bootstrap token.';
        setAuthError(msg);
        setBootstrapRequired(true);
        try {
          sessionStorage.removeItem('laptop_ai_session_token');
        } catch {}
      }
    } catch (err: any) {
      setAuthError('Connection error: could not reach authentication backend.');
      setBootstrapRequired(true);
    }
    return '';
  }

  async function ensureSession(): Promise<string> {
    if (localSessionToken) return localSessionToken;
    try {
      let cached = sessionStorage.getItem('laptop_ai_session_token');
      if (cached) {
        setLocalSessionToken(cached);
        return cached;
      }
    } catch {}
    return await authorizeWithKey();
  }

  async function revokeSession() {
    try {
      if (localSessionToken) {
        await fetch(API + '/auth/revoke', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Session-Token': localSessionToken,
          },
        });
      }
    } catch {}
    try {
      sessionStorage.removeItem('laptop_ai_session_token');
      sessionStorage.removeItem('laptop_ai_bootstrap_token');
    } catch {}
    setLocalSessionToken('');
    setBootstrapRequired(true);
    Z('Session locked / revoked. Re-authorization required.');
  }

  async function req(path:string,init?:RequestInit) {
    let token = localSessionToken;
    if (!token && !path.startsWith('/auth/session')) {
      token = await ensureSession();
    }
    let headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(token ? { 'X-Session-Token': token } : {}),
      ...(init?.headers as Record<string, string> || {}),
    };
    let r = await fetch(API+path,{...init, headers});
    if (r.status === 401 && !path.startsWith('/auth/session')) {
      setLocalSessionToken('');
      setBootstrapRequired(true);
    }
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
      if (page === 'Desktop') {
        await loadDesktopData();
      }
      if (page === 'Visual AI') {
        await loadVisionData();
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

  // Desktop Action Handlers
  async function loadDesktopData() {
    try {
      let [st, wins, shots, hist] = await Promise.all([
        req('/desktop/status').catch(() => ({ available: false })),
        req('/desktop/windows').catch(() => []),
        req('/desktop/screenshots').catch(() => []),
        req('/desktop/history').catch(() => []),
      ]);
      setDStatus(st);
      setDWindows(wins);
      setDScreenshots(shots);
      setDHistory(hist);
      if (shots && shots.length > 0 && !dCurrentScreenshot) {
        setDCurrentScreenshot(`${API}/desktop/screenshot/view?path=${encodeURIComponent(shots[0].path)}`);
      }
    } catch (e: any) {
      Z(`Desktop load error: ${e.message}`);
    }
  }

  async function captureDesktopScreen(target: 'desktop' | 'window' = 'desktop') {
    setDLoading(true);
    try {
      let res = await req('/desktop/screenshot', {
        method: 'POST',
        body: JSON.stringify({ target, hwnd: target === 'window' ? dStatus?.active_window?.hwnd : undefined }),
      });
      if (res && res.path) {
        setDCurrentScreenshot(`${API}/desktop/screenshot/view?path=${encodeURIComponent(res.path)}&t=${Date.now()}`);
        Z(`Captured ${target} screenshot: ${res.filename}`);
      }
      await loadDesktopData();
    } catch (e: any) {
      Z(`Screenshot error: ${e.message}`);
    } finally {
      setDLoading(false);
    }
  }

  async function focusDesktopWindow(hwnd: number, title?: string) {
    setDLoading(true);
    try {
      let res = await req('/desktop/windows/focus', {
        method: 'POST',
        body: JSON.stringify({ hwnd, title }),
      });
      Z(`Focused window: ${res.title || title || hwnd}`);
      await loadDesktopData();
    } catch (e: any) {
      Z(`Focus error: ${e.message}`);
    } finally {
      setDLoading(false);
    }
  }

  async function inspectDesktopWindow(hwnd?: number) {
    setDLoading(true);
    try {
      let res = await req('/desktop/inspect', {
        method: 'POST',
        body: JSON.stringify({ hwnd, max_depth: 3, max_elements: 40 }),
      });
      setDInspection(res);
      Z(`Inspected UI: found ${res.elements_count || 0} accessible controls`);
    } catch (e: any) {
      Z(`UI inspection error: ${e.message}`);
    } finally {
      setDLoading(false);
    }
  }

  async function executeDesktopAction(action_type: string, params: any) {
    setDLoading(true);
    try {
      let res = await req('/desktop/action', {
        method: 'POST',
        body: JSON.stringify({ action_type, params }),
      });
      Z(`Desktop action (${action_type}) executed successfully.`);
      await loadDesktopData();
      return res;
    } catch (e: any) {
      Z(`Action error: ${e.message}`);
    } finally {
      setDLoading(false);
    }
  }

  // Visual Desktop Intelligence Helpers (Queue 2)
  async function loadVisionData() {
    try {
      const [hist, shots] = await Promise.all([
        req('/vision/history'),
        req('/desktop/screenshots')
      ]);
      setVHistory(hist || []);
      setDScreenshots(shots || []);
      if (shots && shots.length > 0 && !vScreenshotThumb) {
        let view = await req(`/desktop/screenshot/view?path=${encodeURIComponent(shots[0].path)}`);
        if (view?.thumbnail_base64) {
          setVScreenshotThumb(`data:image/jpeg;base64,${view.thumbnail_base64}`);
        }
      }
    } catch (e: any) {
      console.warn('Failed to load vision data:', e);
    }
  }

  async function analyzeScreenAction() {
    setVLoading(true);
    Z('');
    try {
      let res = await req('/vision/analyze', {
        method: 'POST',
        body: JSON.stringify({ target: vTarget, use_multimodal: true })
      });
      setVAnalysis(res);
      Z(`Visual analysis complete (${res.analysis_provider || 'local'}): ${res.detected_elements?.length || 0} elements found.`);
      if (res.image_path) {
        let view = await req(`/desktop/screenshot/view?path=${encodeURIComponent(res.image_path)}`);
        if (view?.thumbnail_base64) {
          setVScreenshotThumb(`data:image/jpeg;base64,${view.thumbnail_base64}`);
        }
      }
      await loadVisionData();
    } catch (e: any) {
      Z(`Vision Analysis Error: ${e.message}`);
    } finally {
      setVLoading(false);
    }
  }

  async function extractOcrAction() {
    setVLoading(true);
    Z('');
    try {
      let res = await req('/vision/ocr', {
        method: 'POST',
        body: JSON.stringify({ target: vTarget })
      });
      setVOcr(res);
      setVActiveTab('ocr');
      Z(`OCR Extraction complete: ${res.line_count || 0} lines extracted.`);
      if (res.image_path) {
        let view = await req(`/desktop/screenshot/view?path=${encodeURIComponent(res.image_path)}`);
        if (view?.thumbnail_base64) {
          setVScreenshotThumb(`data:image/jpeg;base64,${view.thumbnail_base64}`);
        }
      }
    } catch (e: any) {
      Z(`OCR Error: ${e.message}`);
    } finally {
      setVLoading(false);
    }
  }

  async function findVisualElementAction() {
    if (!vGroundingQuery.trim()) return;
    setVLoading(true);
    Z('');
    try {
      let res = await req('/vision/find', {
        method: 'POST',
        body: JSON.stringify({ query: vGroundingQuery, target: vTarget })
      });
      setVGrounding(res);
      if (res.found && res.matched_element) {
        setVSelectedElement(res.matched_element);
        setVActiveTab('elements');
        Z(`Element located: "${res.matched_element.label}" (${res.matched_element.element_type}) with ${Math.round(res.confidence * 100)}% confidence.`);
      } else {
        Z(`Element not found for query: "${vGroundingQuery}".`);
      }
    } catch (e: any) {
      Z(`Locate Error: ${e.message}`);
    } finally {
      setVLoading(false);
    }
  }

  async function compareScreenshotsAction() {
    if (!vCompareBase || !vCompareTarget) {
      Z('Select two screenshots to compare.');
      return;
    }
    setVLoading(true);
    Z('');
    try {
      let res = await req('/vision/compare', {
        method: 'POST',
        body: JSON.stringify({ image_path_1: vCompareBase, image_path_2: vCompareTarget })
      });
      setVComparison(res);
      setVActiveTab('compare');
      Z(`Screenshot comparison: ${res.change_percentage}% diff (${res.changed ? 'Changed' : 'Identical'}).`);
    } catch (e: any) {
      Z(`Comparison Error: ${e.message}`);
    } finally {
      setVLoading(false);
    }
  }

  async function cleanupScreenshotsAction() {
    setVLoading(true);
    try {
      let res = await req('/vision/cleanup', {
        method: 'POST',
        body: JSON.stringify({ max_age_hours: 24, keep_latest: 15 })
      });
      Z(`Cleaned up ${res.deleted_count || 0} old screenshots.`);
      await loadVisionData();
    } catch (e: any) {
      Z(`Cleanup Error: ${e.message}`);
    } finally {
      setVLoading(false);
    }
  }

  // File Intelligence Action Handlers (Queue 3)
  async function searchFilesAction() {
    if (!fSearchQuery.trim()) return;
    setFSearchLoading(true);
    try {
      const fmtParam = fSearchFormat !== 'all' ? `&format_filter=${encodeURIComponent(fSearchFormat)}` : '';
      const data = await req(`/files/search?query=${encodeURIComponent(fSearchQuery)}&limit=15${fmtParam}`);
      setFSearchResults(data.results || []);
    } catch (e: any) {
      Z(e.message || 'File search failed');
    } finally {
      setFSearchLoading(false);
    }
  }

  async function extractDocAction() {
    if (!fDocPath.trim()) return;
    setFDocLoading(true);
    try {
      const data = await req('/files/extract', { method: 'POST', body: JSON.stringify({ path: fDocPath }) });
      setFDocParsed(data);
    } catch (e: any) {
      Z(e.message || 'Document extraction failed');
    } finally {
      setFDocLoading(false);
    }
  }

  async function summarizeDocAction() {
    if (!fDocPath.trim()) return;
    setFDocLoading(true);
    try {
      const data = await req('/files/summarize', { method: 'POST', body: JSON.stringify({ path: fDocPath, max_sentences: 5 }) });
      setFDocSummary(data);
    } catch (e: any) {
      Z(e.message || 'Document summarization failed');
    } finally {
      setFDocLoading(false);
    }
  }

  async function askDocAction() {
    if (!fDocPath.trim() || !fDocQuestion.trim()) return;
    setFDocLoading(true);
    try {
      const data = await req('/files/ask', { method: 'POST', body: JSON.stringify({ path: fDocPath, question: fDocQuestion }) });
      setFDocAnswer(data);
    } catch (e: any) {
      Z(e.message || 'Ask document failed');
    } finally {
      setFDocLoading(false);
    }
  }

  async function profileSpreadsheetAction(sheet?: string) {
    if (!fSsPath.trim()) return;
    setFSsLoading(true);
    try {
      const data = await req('/files/spreadsheet/analyze', { method: 'POST', body: JSON.stringify({ path: fSsPath, sheet_name: sheet || undefined }) });
      setFSsProfile(data);
      if (data.active_sheet) setFSsActiveSheet(data.active_sheet);
    } catch (e: any) {
      Z(e.message || 'Spreadsheet profiling failed');
    } finally {
      setFSsLoading(false);
    }
  }

  async function querySpreadsheetAction() {
    if (!fSsPath.trim()) return;
    setFSsLoading(true);
    try {
      const data = await req('/files/spreadsheet/query', {
        method: 'POST',
        body: JSON.stringify({
          path: fSsPath,
          sheet_name: fSsActiveSheet || undefined,
          filter_col: fSsFilterCol || undefined,
          filter_val: fSsFilterVal || undefined,
          sort_by: fSsSortBy || undefined,
          limit: 50
        })
      });
      if (fSsProfile) {
        setFSsProfile({ ...fSsProfile, preview_rows: data.results });
      }
    } catch (e: any) {
      Z(e.message || 'Spreadsheet query failed');
    } finally {
      setFSsLoading(false);
    }
  }

  async function compareDocsAction() {
    if (!fCmpFileA.trim() || !fCmpFileB.trim()) return;
    setFCmpLoading(true);
    try {
      const data = await req('/files/compare', { method: 'POST', body: JSON.stringify({ file_a: fCmpFileA, file_b: fCmpFileB }) });
      setFCmpResult(data);
    } catch (e: any) {
      Z(e.message || 'Document comparison failed');
    } finally {
      setFCmpLoading(false);
    }
  }

  async function findDuplicatesAction() {
    setFOrgLoading(true);
    try {
      const data = await req('/files/duplicates', { method: 'POST', body: JSON.stringify({ folder_path: fOrgFolder, max_files: 300 }) });
      setFOrgDuplicates(data || []);
    } catch (e: any) {
      Z(e.message || 'Duplicate scan failed');
    } finally {
      setFOrgLoading(false);
    }
  }

  async function previewOrgAction() {
    setFOrgLoading(true);
    try {
      const data = await req('/files/organize/preview', { method: 'POST', body: JSON.stringify({ folder_path: fOrgFolder }) });
      setFOrgPreview(data);
    } catch (e: any) {
      Z(e.message || 'Organization preview failed');
    } finally {
      setFOrgLoading(false);
    }
  }

  async function executeOrgAction() {
    if (!fOrgPreview?.proposed_actions?.length) return;
    setFOrgLoading(true);
    try {
      const res = await req('/files/organize/execute', {
        method: 'POST',
        body: JSON.stringify({ action_items: fOrgPreview.proposed_actions })
      });
      Z(`Executed file organization: ${res.executed_count} actions completed.`);
      previewOrgAction();
    } catch (e: any) {
      Z(e.message || 'Organization execution failed');
    } finally {
      setFOrgLoading(false);
    }
  }

  async function refreshIndexAction() {
    setFIdxLoading(true);
    try {
      const res = await req('/files/index/refresh', {
        method: 'POST',
        body: JSON.stringify({ path: fIdxFolder, recursive: true, max_files: 100 })
      });
      Z(`Index refreshed: ${res.indexed || 0} indexed, ${res.skipped || 0} skipped.`);
      loadIndexStatusAction();
    } catch (e: any) {
      Z(e.message || 'Index refresh failed');
    } finally {
      setFIdxLoading(false);
    }
  }

  async function loadIndexStatusAction() {
    try {
      const data = await req('/files/index/status');
      setFIdxStatus(data);
    } catch (e: any) {
      // ignore
    }
  }

  // Assistant Action Handlers (Queue 4)
  async function loadAssistantData() {
    try {
      setAsBriefingLoading(true);
      let [b, r, m, n, p, pl] = await Promise.all([
        req('/assistant/briefing').catch(() => null),
        req('/assistant/reminders').catch(() => []),
        req('/assistant/monitors').catch(() => []),
        req('/assistant/notifications').catch(() => []),
        req('/assistant/profile').catch(() => null),
        req('/assistant/plan/daily').catch(() => null),
      ]);
      setAsBriefing(b);
      setAsReminders(r || []);
      setAsMonitors(m || []);
      setAsNotifications(n || []);
      setAsProfile(p);
      setAsDailyPlan(pl);
      if (Array.isArray(n)) {
        setAsUnreadCount(n.filter((item: any) => !item.read_status && !item.dismissed).length);
      }
    } catch (e: any) {
      console.error('Failed to load assistant data:', e);
    } finally {
      setAsBriefingLoading(false);
    }
  }

  async function snoozeReminder(id: string, mins: number) {
    try {
      await req(`/assistant/reminders/${id}/snooze`, {
        method: 'POST',
        body: JSON.stringify({ snooze_minutes: mins }),
      });
      Z(`Reminder snoozed for ${mins} minutes.`);
      loadAssistantData();
    } catch (e: any) {
      Z(`Snooze failed: ${e.message}`);
    }
  }

  async function dismissReminder(id: string) {
    try {
      await req(`/assistant/reminders/${id}/dismiss`, { method: 'POST' });
      Z('Reminder dismissed.');
      loadAssistantData();
    } catch (e: any) {
      Z(`Dismiss failed: ${e.message}`);
    }
  }

  async function createReminderAction() {
    if (!remTitle.trim() || !remDueAt.trim()) {
      Z('Title and due time are required.');
      return;
    }
    try {
      await req('/assistant/reminders', {
        method: 'POST',
        body: JSON.stringify({
          title: remTitle.trim(),
          due_at: remDueAt,
          reminder_type: remType,
        }),
      });
      setRemTitle('');
      setRemDueAt('');
      Z('Reminder created successfully.');
      loadAssistantData();
    } catch (e: any) {
      Z(`Failed to create reminder: ${e.message}`);
    }
  }

  async function toggleMonitor(id: string, enabled: boolean) {
    try {
      await req(`/assistant/monitors/${id}/toggle`, {
        method: 'POST',
        body: JSON.stringify({ enabled }),
      });
      Z(`Monitor ${enabled ? 'enabled' : 'paused'}.`);
      loadAssistantData();
    } catch (e: any) {
      Z(`Toggle failed: ${e.message}`);
    }
  }

  async function deleteMonitor(id: string) {
    try {
      await req(`/assistant/monitors/${id}`, { method: 'DELETE' });
      Z('Monitor deleted.');
      loadAssistantData();
    } catch (e: any) {
      Z(`Delete failed: ${e.message}`);
    }
  }

  async function createMonitorAction() {
    if (!monName.trim()) {
      Z('Monitor name required.');
      return;
    }
    try {
      await req('/assistant/monitors', {
        method: 'POST',
        body: JSON.stringify({
          name: monName.trim(),
          monitor_type: monType,
          target_identifier: monTarget.trim() || '*',
          threshold_seconds: Number(monThreshold) || 3600,
        }),
      });
      setMonName('');
      Z('Monitor created successfully.');
      loadAssistantData();
    } catch (e: any) {
      Z(`Failed to create monitor: ${e.message}`);
    }
  }

  async function dismissNotification(id: string) {
    try {
      await req(`/assistant/notifications/${id}/dismiss`, { method: 'POST' });
      loadAssistantData();
    } catch (e: any) {
      Z(`Dismiss notification failed: ${e.message}`);
    }
  }

  async function confirmProfileItem(key: string, val: any, cat: string) {
    try {
      await req('/assistant/profile', {
        method: 'POST',
        body: JSON.stringify({
          key,
          value: val,
          category: cat,
          is_confirmed: true,
          confidence: 1.0,
          source: 'user_confirmed',
        }),
      });
      Z(`Confirmed preference: ${key}`);
      loadAssistantData();
    } catch (e: any) {
      Z(`Failed to confirm preference: ${e.message}`);
    }
  }

  async function createProfileItem() {
    if (!newPrefKey.trim()) return;
    try {
      await req('/assistant/profile', {
        method: 'POST',
        body: JSON.stringify({
          key: newPrefKey.trim(),
          value: newPrefVal.trim(),
          category: newPrefCat,
          is_confirmed: true,
        }),
      });
      setNewPrefKey('');
      setNewPrefVal('');
      Z('Preference saved.');
      loadAssistantData();
    } catch (e: any) {
      Z(`Save failed: ${e.message}`);
    }
  }

  async function createNaturalTaskAction() {
    if (!natTaskInput.trim()) return;
    try {
      let payload: any = { user_request: natTaskInput.trim() };
      if (natTaskPriority) payload.priority = natTaskPriority;
      let res = await req('/assistant/tasks/natural', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setNatTaskInput('');
      setNatTaskPriority('');
      Z(`Task created: "${res.title}" [${res.priority}]`);
      loadAssistantData();
    } catch (e: any) {
      Z(`Task creation failed: ${e.message}`);
    }
  }

  useEffect(() => {
    refresh();
    if (page === 'Files') {
      loadIndexStatusAction();
    }
    if (page === 'Assistant') {
      loadAssistantData();
    }
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
        {nav.slice(0,3).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}
            {n==='Assistant'&&asUnreadCount>0&&<small className="notif-badge">{asUnreadCount}</small>}
          </button>
        ))}
        <div className="navlabel">CONTROL CENTER</div>
        {nav.slice(3,7).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}
          </button>
        ))}
        <div className="navlabel">PREFERENCES & TOOLS</div>
        {nav.slice(7).map(([n,I]:any)=>(
          <button key={n} className={'nav '+(page===n?'selected':'')} onClick={()=>P(n)}>
            <I size={17}/>{n}{n==='Tool Registry'&&<small className="count">{tools.length}</small>}
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
            {localSessionToken ? (
              <button
                className="ghost"
                onClick={revokeSession}
                title="Lock session / Sign out"
                style={{padding:'4px 8px',fontSize:11,display:'flex',alignItems:'center',gap:4,color:'#c084fc'}}
              >
                <Lock size={13} /> Lock
              </button>
            ) : null}
            <button className="ghost" onClick={() => { P('Assistant'); setAsTab('notifications'); }} title="Notifications">
              <Bell size={16}/>
              {asUnreadCount > 0 && <span className="notif-badge">{asUnreadCount}</span>}
            </button>
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

        {bootstrapRequired && !localSessionToken && (
          <div style={{background:'#1e1528',border:'1px solid #7c3aed',borderRadius:8,padding:'12px 16px',margin:'10px 20px',display:'flex',alignItems:'center',justifyContent:'space-between',gap:12}}>
            <div style={{display:'flex',alignItems:'center',gap:10}}>
              <ShieldCheck size={20} color="#a855f7"/>
              <div>
                <b style={{color:'#e9d5ff',fontSize:13}}>Local Authorization Required</b>
                <div style={{color:'#c084fc',fontSize:11}}>
                  Enter local bootstrap secret from <code>%USERPROFILE%\.laptop_ai\bootstrap.token</code> (or <code>LAPTOP_AI_BOOTSTRAP_SECRET</code>) to authorize this browser session.
                </div>
                {authError && <div style={{color:'#f87171',fontSize:11,marginTop:4,fontWeight:500}}>{authError}</div>}
              </div>
            </div>
            <div style={{display:'flex',gap:8}}>
              <input
                type="password"
                placeholder="Paste bootstrap secret..."
                value={manualBootstrapKey}
                onChange={e=>setManualBootstrapKey(e.target.value)}
                onKeyDown={e=>{ if (e.key === 'Enter') authorizeWithKey(manualBootstrapKey); }}
                style={{background:'#0f0c1b',border:'1px solid #581c87',borderRadius:6,padding:'6px 10px',color:'#fff',fontSize:12,width:260}}
              />
              <button className="primary" onClick={()=>authorizeWithKey(manualBootstrapKey)} style={{padding:'6px 14px',fontSize:12}}>Authorize</button>
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

          {page==='Desktop'&&<>
            <Heading tag="WINDOWS AUTOMATION" title="Desktop control engine" desc="Inspect application windows, capture screen telemetry, navigate accessible UI controls, and execute approved mouse/keyboard actions." action={
              <div style={{display:'flex',gap:'8px'}}>
                <button className="secondary" onClick={()=>captureDesktopScreen('desktop')} disabled={dLoading}><Camera size={14}/> Capture screen</button>
                <button className="secondary" onClick={()=>captureDesktopScreen('window')} disabled={dLoading}><Monitor size={14}/> Capture active app</button>
                <button className="primary" onClick={loadDesktopData} disabled={dLoading}><RefreshCw size={14}/> Refresh</button>
              </div>
            }/>

            <div className="stats registry-stats">
              <Stat icon={Monitor} label="Desktop session" value={dStatus?.available ? 'Interactive' : 'Locked / Unavailable'} note={dStatus?.is_locked ? 'Workstation Locked' : 'WinSta0\\default'}/>
              <Stat icon={Activity} label="Active application" value={dStatus?.active_window?.process || 'None'} note={dStatus?.active_window?.title ? (dStatus.active_window.title.slice(0, 24) + '...') : 'Idle desktop'}/>
              <Stat icon={Workflow} label="Open windows" value={dWindows.length} note={`Display: ${dStatus?.display?.width || 1366} × ${dStatus?.display?.height || 768}`}/>
              <Stat icon={ShieldCheck} label="Emergency state" value={emergency.is_stopped ? 'ENGAGED' : 'Clear'} note={emergency.is_stopped ? 'All actions halted' : 'Approval gates active'}/>
            </div>

            <div className="desktop-layout">
              <div>
                {/* Visual Viewport & Preview */}
                <div className="panel" style={{padding:'14px'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'10px'}}>
                    <h3 style={{margin:0,fontSize:'13px'}}>Desktop Visual Display</h3>
                    <div style={{display:'flex',gap:'6px'}}>
                      <button className="ghost" style={{fontSize:'10px'}} onClick={()=>inspectDesktopWindow()} disabled={dLoading}>
                        <Search size={12}/> Inspect active UI
                      </button>
                    </div>
                  </div>
                  <div className="desktop-preview-box">
                    {dCurrentScreenshot ? (
                      <img src={dCurrentScreenshot} alt="Windows Desktop Telemetry Preview" style={{maxHeight:'340px',objectFit:'contain'}}/>
                    ) : (
                      <div style={{textAlign:'center',color:'#55637a',padding:'50px 0'}}>
                        <Monitor size={36} style={{marginBottom:'10px',opacity:0.4}}/>
                        <p style={{fontSize:'11px',margin:0}}>No screenshot taken yet. Click 'Capture screen' above.</p>
                      </div>
                    )}
                  </div>
                  {dScreenshots.length > 0 && (
                    <div style={{display:'flex',gap:'6px',overflowX:'auto',marginTop:'10px',paddingBottom:'4px'}}>
                      {dScreenshots.slice(0, 6).map((s:any, idx:number)=>(
                        <div key={idx} onClick={()=>setDCurrentScreenshot(`${API}/desktop/screenshot/view?path=${encodeURIComponent(s.path)}`)}
                          style={{border:'1px solid #283446',borderRadius:'4px',padding:'4px 6px',fontSize:'9px',cursor:'pointer',whiteSpace:'nowrap',background:'#101723'}}>
                          <Camera size={10} style={{marginRight:'4px',verticalAlign:'middle'}}/>
                          {s.filename.slice(0, 18)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Accessible UI Inspector Panel */}
                <div className="panel" style={{padding:'14px',marginTop:'14px'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                    <div>
                      <h3 style={{margin:0,fontSize:'13px'}}>Accessible UI Elements</h3>
                      <small style={{color:'#7d899d',fontSize:'9px'}}>
                        {dInspection?.accessible ? `${dInspection.elements_count} controls in "${dInspection.window?.title?.slice(0, 30)}..."` : (dInspection ? 'Non-accessible application' : 'Click Inspect to view accessible elements')}
                      </small>
                    </div>
                    <button className="secondary" style={{padding:'4px 10px',fontSize:'9px'}} onClick={()=>inspectDesktopWindow()} disabled={dLoading}>
                      <RefreshCw size={11}/> Inspect active window
                    </button>
                  </div>

                  {dInspection?.accessible && dInspection.elements?.length > 0 ? (
                    <div className="desktop-ui-table">
                      {dInspection.elements.map((el:any, idx:number)=>(
                        <div className="desktop-ui-row" key={idx}>
                          <div style={{display:'flex',alignItems:'center',gap:'8px',minWidth:0,flex:1}}>
                            <span className="desktop-tag">{el.control_type}</span>
                            <span style={{fontWeight:600,color:'#e2e8f0',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}} title={el.name}>
                              {el.name || '(unnamed control)'}
                            </span>
                            {el.patterns?.map((p:string, pidx:number)=>(
                              <span key={pidx} className="desktop-pattern-pill">{p}</span>
                            ))}
                          </div>
                          <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
                            <span style={{fontSize:'8px',color:'#64748b'}}>[{el.center?.x}, {el.center?.y}]</span>
                            <button className="primary" style={{padding:'3px 8px',fontSize:'8px'}} onClick={()=>executeDesktopAction('click', { element_query: el.name, control_type: el.control_type })} disabled={dLoading}>
                              <MousePointer size={9}/> Click
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{fontSize:'10px',color:'#78869c',margin:'8px 0'}}>
                      {dInspection?.reason || 'Select or focus an application window and click Inspect active window to enumerate buttons, text fields, and tabs.'}
                    </p>
                  )}
                </div>
              </div>

              <div>
                {/* Open Application Windows */}
                <div className="panel" style={{padding:'14px'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                    <h3 style={{margin:0,fontSize:'13px'}}>Open Windows ({dWindows.length})</h3>
                    <input
                      style={{maxWidth:'180px',padding:'4px 8px',fontSize:'9px'}}
                      placeholder="Filter windows..."
                      value={dWindowFilter}
                      onChange={e=>setDWindowFilter(e.target.value)}
                    />
                  </div>
                  <div style={{maxHeight:'260px',overflowY:'auto',display:'flex',flexDirection:'column',gap:'4px'}}>
                    {dWindows
                      .filter((w:any)=>!dWindowFilter.trim() || w.title.toLowerCase().includes(dWindowFilter.toLowerCase()) || w.process.toLowerCase().includes(dWindowFilter.toLowerCase()))
                      .map((w:any)=>(
                        <div key={w.hwnd} className={'desktop-window-item ' + (dStatus?.active_window?.hwnd === w.hwnd ? 'active' : '')}>
                          <div className="desktop-window-info">
                            <b title={w.title}>{w.title}</b>
                            <small>
                              <span className="desktop-tag proc">{w.process}</span>
                              <span>PID {w.pid}</span>
                              <span>HWND {w.hwnd}</span>
                              {w.is_minimized && <span style={{color:'#fbbf24'}}>Minimized</span>}
                            </small>
                          </div>
                          <div style={{display:'flex',gap:'4px'}}>
                            <button className="secondary" style={{padding:'4px 8px',fontSize:'8px'}} onClick={()=>focusDesktopWindow(w.hwnd, w.title)} disabled={dLoading}>
                              Focus
                            </button>
                            <button className="ghost" style={{padding:'4px 6px',fontSize:'8px'}} onClick={()=>inspectDesktopWindow(w.hwnd)} title="Inspect UI" disabled={dLoading}>
                              <Search size={11}/>
                            </button>
                          </div>
                        </div>
                      ))}
                    {!dWindows.length && <p style={{fontSize:'10px',color:'#64748b',margin:'8px 0'}}>No visible application windows detected.</p>}
                  </div>
                </div>

                {/* Quick Desktop Actions & Keyboard Shortcuts */}
                <div className="panel" style={{padding:'14px',marginTop:'14px'}}>
                  <h3 style={{margin:'0 0 6px',fontSize:'13px'}}>Quick Desktop Actions</h3>
                  <small style={{color:'#78869c',fontSize:'9px',display:'block',marginBottom:'10px'}}>
                    Execute approved keyboard input and shortcuts directly into the focused window.
                  </small>
                  
                  <div style={{display:'flex',gap:'6px',marginBottom:'12px'}}>
                    <input
                      style={{flex:1,padding:'7px 10px',fontSize:'10px'}}
                      placeholder="Type text into active field..."
                      value={dTypeText}
                      onChange={e=>setDTypeText(e.target.value)}
                      onKeyDown={e=>{if(e.key==='Enter'&&dTypeText.trim()){executeDesktopAction('type', { text: dTypeText, press_enter: true });setDTypeText('');}}}
                    />
                    <button className="primary" style={{padding:'0 12px',fontSize:'9px'}} onClick={()=>{if(dTypeText.trim()){executeDesktopAction('type', { text: dTypeText });setDTypeText('');}}} disabled={dLoading||!dTypeText.trim()}>
                      <Keyboard size={11}/> Type
                    </button>
                  </div>

                  <label style={{fontSize:'8px',fontWeight:700,letterSpacing:'1px',color:'#8994a8',display:'block',marginBottom:'4px'}}>APPROVED SHORTCUTS</label>
                  <div className="desktop-shortcuts-grid">
                    {[
                      {label:'Save (Ctrl+S)', keys:['ctrl','s']},
                      {label:'Copy (Ctrl+C)', keys:['ctrl','c']},
                      {label:'Paste (Ctrl+V)', keys:['ctrl','v']},
                      {label:'Undo (Ctrl+Z)', keys:['ctrl','z']},
                      {label:'Find (Ctrl+F)', keys:['ctrl','f']},
                      {label:'Select All (Ctrl+A)', keys:['ctrl','a']},
                      {label:'Enter', keys:['enter']},
                      {label:'Escape', keys:['escape']},
                      {label:'Tab', keys:['tab']},
                      {label:'Switch App (Alt+Tab)', keys:['alt','tab']},
                      {label:'New Tab (Ctrl+T)', keys:['ctrl','t']},
                      {label:'Close Tab (Ctrl+W)', keys:['ctrl','w']},
                    ].map((sc:any, sidx:number)=>(
                      <button key={sidx} className="desktop-shortcut-btn" onClick={()=>executeDesktopAction('press', { keys: sc.keys })} disabled={dLoading}>
                        {sc.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Desktop Action History & Pending Approvals */}
                <div className="panel" style={{padding:'14px',marginTop:'14px'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                    <h3 style={{margin:0,fontSize:'13px'}}>Recent Desktop Actions</h3>
                    <small style={{color:'#64748b',fontSize:'9px'}}>Audit feed</small>
                  </div>
                  <div style={{maxHeight:'160px',overflowY:'auto',display:'flex',flexDirection:'column'}}>
                    {dHistory.map((h:any, hidx:number)=>(
                      <div key={hidx} className="desktop-history-item">
                        <div>
                          <b style={{color:h.success?'#6ee7b7':'#f87171',fontSize:'9px'}}>{h.action_type}</b>
                          <small style={{display:'block',color:'#64748b',fontSize:'8px'}}>{h.timestamp?.slice(11, 19)}</small>
                        </div>
                        <span style={{fontSize:'8px',color:'#94a3b8',maxWidth:'160px',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                          {JSON.stringify(h.details)}
                        </span>
                      </div>
                    ))}
                    {!dHistory.length && <p style={{fontSize:'9px',color:'#55637a',margin:'6px 0'}}>No desktop actions recorded yet.</p>}
                  </div>
                </div>
              </div>
            </div>
          </>}

          {page==='Visual AI'&&<>
            <Heading tag="COMPUTER VISION" title="Visual desktop intelligence" desc="Analyze screen contents, extract OCR text, detect UI components, locate visual targets, and compare desktop states." action={
              <div style={{display:'flex',gap:'8px'}}>
                <button className="secondary" onClick={()=>setVTarget(vTarget==='desktop'?'window':'desktop')} disabled={vLoading}>
                  <Monitor size={14}/> Target: {vTarget==='desktop'?'Full Desktop':'Active Window'}
                </button>
                <button className="secondary" onClick={extractOcrAction} disabled={vLoading}>
                  <Terminal size={14}/> Extract Text (OCR)
                </button>
                <button className="primary" onClick={analyzeScreenAction} disabled={vLoading}>
                  <Sparkles size={14}/> {vLoading ? 'Analyzing...' : 'Analyze Screen'}
                </button>
              </div>
            }/>

            <div className="stats registry-stats">
              <Stat icon={Eye} label="Vision engine" value={providers?.gemini?.configured ? 'Gemini 2.5 Flash' : 'Local OCR Fused'} note={providers?.gemini?.configured ? 'Multimodal Active' : 'Deterministic Local Fallback'}/>
              <Stat icon={Boxes} label="Detected elements" value={vAnalysis?.detected_elements?.length || 0} note={vAnalysis?.error_dialogs?.length ? `${vAnalysis.error_dialogs.length} Warnings/Errors` : 'No error dialogs'}/>
              <Stat icon={Activity} label="Active application" value={vAnalysis?.active_application || 'Windows'} note={vAnalysis?.window_title ? (vAnalysis.window_title.slice(0, 24) + '...') : 'Desktop Viewport'}/>
              <Stat icon={ShieldCheck} label="Security boundary" value={emergency.is_stopped ? 'HALTED' : 'Read-Only'} note="Zero autonomous actions"/>
            </div>

            <div className="vision-layout">
              <div>
                {/* Viewport with Bounding Box Overlay */}
                <div className="panel" style={{padding:'14px'}}>
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'10px'}}>
                    <div>
                      <h3 style={{margin:0,fontSize:'13px'}}>Visual Screen Viewport</h3>
                      <small style={{color:'#7d899d',fontSize:'9px'}}>
                        {vSelectedElement ? `Selected: "${vSelectedElement.label}" (${vSelectedElement.element_type}) at [${vSelectedElement.bbox?.center?.[0]}, ${vSelectedElement.bbox?.center?.[1]}]` : 'Interactive bounding boxes overlaid on screen telemetry'}
                      </small>
                    </div>
                    <div style={{display:'flex',gap:'6px'}}>
                      <button className="ghost" style={{fontSize:'10px'}} onClick={loadVisionData} disabled={vLoading}>
                        <RefreshCw size={12}/> Refresh view
                      </button>
                    </div>
                  </div>

                  <div className="vision-viewport">
                    {vScreenshotThumb ? (
                      <div style={{position:'relative',width:'100%'}}>
                        <img src={vScreenshotThumb} alt="Desktop Visual Telemetry" style={{width:'100%',display:'block'}}/>
                        {/* Bounding box overlays */}
                        {vAnalysis?.detected_elements?.map((el: any, idx: number) => {
                          const norm = el.bbox?.normalized || [];
                          if (norm.length !== 4) return null;
                          const [x1, y1, x2, y2] = norm;
                          const leftPct = `${x1 * 100}%`;
                          const topPct = `${y1 * 100}%`;
                          const widthPct = `${Math.max(1, (x2 - x1) * 100)}%`;
                          const heightPct = `${Math.max(1, (y2 - y1) * 100)}%`;
                          const isSelected = vSelectedElement?.id === el.id;

                          let typeClass = 'btn';
                          if (el.element_type === 'text_input') typeClass = 'input';
                          else if (el.element_type === 'menu') typeClass = 'menu';
                          else if (el.element_type === 'error_warning') typeClass = 'error';

                          return (
                            <div
                              key={idx}
                              className={`vision-overlay-box ${typeClass} ${isSelected ? 'selected' : ''}`}
                              style={{left: leftPct, top: topPct, width: widthPct, height: heightPct}}
                              onClick={() => { setVSelectedElement(el); setVActiveTab('elements'); }}
                              title={`${el.element_type.toUpperCase()}: ${el.label} (${Math.round(el.confidence * 100)}% confidence)`}
                            />
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{textAlign:'center',color:'#55637a',padding:'60px 0'}}>
                        <Eye size={40} style={{marginBottom:'10px',opacity:0.35}}/>
                        <p style={{fontSize:'12px',margin:0,color:'#94a3b8'}}>No visual telemetry captured yet.</p>
                        <small style={{fontSize:'10px',color:'#64748b'}}>Click "Analyze Screen" or "Extract Text" above to inspect desktop contents.</small>
                      </div>
                    )}
                  </div>

                  {/* Visual Grounding Search Bar */}
                  <div style={{marginTop:'12px',display:'flex',gap:'8px'}}>
                    <input
                      type="text"
                      className="chatinput"
                      placeholder="Find element (e.g. Save button, address bar, error dialog, Cancel)..."
                      value={vGroundingQuery}
                      onChange={e => setVGroundingQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && findVisualElementAction()}
                      style={{flex:1,fontSize:'11px',padding:'8px 12px'}}
                      disabled={vLoading}
                    />
                    <button className="primary" style={{padding:'8px 14px',fontSize:'11px'}} onClick={findVisualElementAction} disabled={vLoading || !vGroundingQuery.trim()}>
                      <Search size={12}/> Locate
                    </button>
                  </div>
                </div>
              </div>

              <div>
                {/* Right Tabbed Inspector */}
                <div className="panel" style={{padding:'14px'}}>
                  <div className="vision-tab-bar">
                    <button className={`vision-tab-btn ${vActiveTab==='analysis'?'active':''}`} onClick={()=>setVActiveTab('analysis')}>
                      <Sparkles size={11} style={{marginRight:'4px'}}/> Screen Analysis
                    </button>
                    <button className={`vision-tab-btn ${vActiveTab==='elements'?'active':''}`} onClick={()=>setVActiveTab('elements')}>
                      <Boxes size={11} style={{marginRight:'4px'}}/> Elements ({vAnalysis?.detected_elements?.length || 0})
                    </button>
                    <button className={`vision-tab-btn ${vActiveTab==='ocr'?'active':''}`} onClick={()=>setVActiveTab('ocr')}>
                      <Terminal size={11} style={{marginRight:'4px'}}/> OCR Text
                    </button>
                    <button className={`vision-tab-btn ${vActiveTab==='compare'?'active':''}`} onClick={()=>setVActiveTab('compare')}>
                      <Repeat size={11} style={{marginRight:'4px'}}/> Compare
                    </button>
                    <button className={`vision-tab-btn ${vActiveTab==='history'?'active':''}`} onClick={()=>setVActiveTab('history')}>
                      <Clock3 size={11} style={{marginRight:'4px'}}/> History
                    </button>
                  </div>

                  {/* Tab 1: Analysis */}
                  {vActiveTab === 'analysis' && (
                    <div>
                      {vAnalysis ? (
                        <div>
                          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                            <span style={{fontSize:'10px',fontWeight:700,color:'#38bdf8',textTransform:'uppercase'}}>
                              {vAnalysis.analysis_provider} Analysis ({vAnalysis.duration_ms}ms)
                            </span>
                            <span style={{fontSize:'9px',color:'#64748b'}}>Target: {vTarget}</span>
                          </div>

                          <div style={{background:'#0c1018',border:'1px solid #1f2a3c',borderRadius:'6px',padding:'12px',fontSize:'11px',lineHeight:'1.6',color:'#e2e8f0',marginBottom:'12px',whiteSpace:'pre-wrap'}}>
                            {vAnalysis.summary}
                          </div>

                          {vAnalysis.visual_warnings?.length > 0 && (
                            <div style={{background:'#4c0519',border:'1px solid #be123c',borderRadius:'6px',padding:'10px',marginBottom:'12px'}}>
                              <div style={{display:'flex',alignItems:'center',gap:'6px',color:'#fda4af',fontSize:'11px',fontWeight:700,marginBottom:'4px'}}>
                                <AlertTriangle size={14}/> Detected Visual Errors / Warnings
                              </div>
                              <ul style={{margin:0,paddingLeft:'18px',fontSize:'10px',color:'#fecdd3'}}>
                                {vAnalysis.visual_warnings.map((w: string, idx: number) => (
                                  <li key={idx}>{w}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {vAnalysis.key_text_snippets?.length > 0 && (
                            <div>
                              <small style={{display:'block',color:'#78869c',fontSize:'9px',fontWeight:700,textTransform:'uppercase',marginBottom:'6px'}}>
                                Prominent On-Screen Text
                              </small>
                              <div style={{display:'flex',flexWrap:'wrap',gap:'4px'}}>
                                {vAnalysis.key_text_snippets.map((snip: string, sidx: number) => (
                                  <span key={sidx} style={{background:'#162030',border:'1px solid #28374e',borderRadius:'4px',padding:'3px 7px',fontSize:'9px',color:'#cbd5e1'}}>
                                    {snip}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p style={{fontSize:'11px',color:'#64748b',textAlign:'center',padding:'40px 0'}}>
                          Click <b>Analyze Screen</b> to inspect running applications, error dialogs, and desktop elements.
                        </p>
                      )}
                    </div>
                  )}

                  {/* Tab 2: Detected Elements */}
                  {vActiveTab === 'elements' && (
                    <div>
                      <div style={{display:'flex',gap:'4px',marginBottom:'8px',overflowX:'auto'}}>
                        {['all', 'button', 'text_input', 'menu', 'error_warning'].map((f) => (
                          <button
                            key={f}
                            className={`desktop-shortcut-btn ${vElementFilter===f?'active':''}`}
                            onClick={()=>setVElementFilter(f)}
                            style={{padding:'3px 7px',fontSize:'8px',textTransform:'capitalize'}}
                          >
                            {f.replace('_', ' ')}
                          </button>
                        ))}
                      </div>

                      <div className="desktop-ui-table" style={{maxHeight:'320px'}}>
                        {vAnalysis?.detected_elements
                          ?.filter((el: any) => vElementFilter === 'all' || el.element_type === vElementFilter)
                          .map((el: any, idx: number) => (
                            <div
                              key={idx}
                              className={`vision-element-card ${vSelectedElement?.id === el.id ? 'active' : ''}`}
                              onClick={()=>setVSelectedElement(el)}
                            >
                              <div style={{display:'flex',alignItems:'center',gap:'6px',minWidth:0,flex:1}}>
                                <span className={`vision-badge ${el.element_type}`}>{el.element_type.replace('_', ' ')}</span>
                                <b style={{color:'#f1f5f9',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}} title={el.label}>
                                  {el.label || '(unnamed element)'}
                                </b>
                                {el.cross_verified_uia && (
                                  <span style={{background:'#064e3b',color:'#6ee7b7',fontSize:'7px',padding:'1px 4px',borderRadius:'3px'}}>UIA Verified</span>
                                )}
                              </div>
                              <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
                                <span style={{fontSize:'9px',color:'#38bdf8',fontWeight:700}}>{Math.round(el.confidence * 100)}%</span>
                                <span style={{fontSize:'8px',color:'#64748b'}}>[{el.bbox?.center?.[0]}, {el.bbox?.center?.[1]}]</span>
                              </div>
                            </div>
                          ))}
                        {!vAnalysis?.detected_elements?.length && (
                          <p style={{fontSize:'10px',color:'#64748b',textAlign:'center',padding:'30px 0'}}>
                            No elements detected. Run "Analyze Screen" to detect UI buttons, inputs, and menus.
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Tab 3: OCR Text */}
                  {vActiveTab === 'ocr' && (
                    <div>
                      {vOcr?.success ? (
                        <div>
                          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                            <span style={{fontSize:'10px',fontWeight:700,color:'#10b981'}}>
                              Extracted {vOcr.line_count} text lines ({vOcr.duration_ms}ms)
                            </span>
                            <span style={{fontSize:'9px',color:'#64748b'}}>Engine: {vOcr.engine_used}</span>
                          </div>
                          <div style={{background:'#080d14',border:'1px solid #1a2334',borderRadius:'6px',padding:'10px',maxHeight:'320px',overflowY:'auto',fontFamily:'monospace',fontSize:'10px',lineHeight:'1.5',color:'#cbd5e1',whiteSpace:'pre-wrap'}}>
                            {vOcr.text || '(No text detected in screenshot)'}
                          </div>
                        </div>
                      ) : (
                        <p style={{fontSize:'11px',color:'#64748b',textAlign:'center',padding:'40px 0'}}>
                          Click <b>Extract Text (OCR)</b> to run Windows native OCR on the current screen.
                        </p>
                      )}
                    </div>
                  )}

                  {/* Tab 4: Visual Compare */}
                  {vActiveTab === 'compare' && (
                    <div>
                      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px',marginBottom:'10px'}}>
                        <div>
                          <small style={{display:'block',fontSize:'9px',color:'#78869c',marginBottom:'4px'}}>Base Screenshot</small>
                          <select
                            className="chatinput"
                            style={{width:'100%',fontSize:'10px',padding:'5px'}}
                            value={vCompareBase}
                            onChange={e => setVCompareBase(e.target.value)}
                          >
                            <option value="">Select screenshot...</option>
                            {dScreenshots.map((s: any, idx: number) => (
                              <option key={idx} value={s.path}>{s.filename} ({s.created_at?.slice(11, 19)})</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <small style={{display:'block',fontSize:'9px',color:'#78869c',marginBottom:'4px'}}>Comparison Screenshot</small>
                          <select
                            className="chatinput"
                            style={{width:'100%',fontSize:'10px',padding:'5px'}}
                            value={vCompareTarget}
                            onChange={e => setVCompareTarget(e.target.value)}
                          >
                            <option value="">Select screenshot...</option>
                            {dScreenshots.map((s: any, idx: number) => (
                              <option key={idx} value={s.path}>{s.filename} ({s.created_at?.slice(11, 19)})</option>
                            ))}
                          </select>
                        </div>
                      </div>

                      <button className="primary" style={{width:'100%',fontSize:'10px',padding:'6px'}} onClick={compareScreenshotsAction} disabled={vLoading || !vCompareBase || !vCompareTarget}>
                        <Repeat size={12}/> Compare Selected Screenshots
                      </button>

                      {vComparison && (
                        <div style={{marginTop:'12px',background:'#0d131e',border:'1px solid #1f2b3e',borderRadius:'6px',padding:'10px'}}>
                          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'6px'}}>
                            <span style={{fontSize:'10px',fontWeight:700,color:vComparison.has_major_layout_change?'#fb7185':'#38bdf8'}}>
                              {vComparison.has_major_layout_change ? 'Major Layout Alteration' : (vComparison.changed ? 'Minor Visual Changes' : 'Visually Identical')}
                            </span>
                            <span style={{fontSize:'10px',color:'#94a3b8'}}>{vComparison.change_percentage}% diff</span>
                          </div>
                          <div className="meter" style={{margin:'6px 0'}}>
                            <i><span style={{width:`${Math.min(100, vComparison.change_percentage * 5)}%`,background:vComparison.has_major_layout_change?'#f43f5e':'#38bdf8'}}/></i>
                          </div>
                          <p style={{fontSize:'10px',color:'#cbd5e1',lineHeight:'1.5',margin:'6px 0'}}>
                            {vComparison.change_summary}
                          </p>
                          {vComparison.changed_regions?.length > 0 && (
                            <small style={{fontSize:'8px',color:'#64748b'}}>
                              Changed regions: {vComparison.changed_regions.length} area(s) detected.
                            </small>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab 5: History */}
                  {vActiveTab === 'history' && (
                    <div>
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                        <h4 style={{margin:0,fontSize:'11px'}}>Analysis History ({vHistory.length})</h4>
                        <div style={{display:'flex',gap:'6px'}}>
                          <button className="secondary" style={{fontSize:'9px',padding:'3px 8px'}} onClick={cleanupScreenshotsAction} disabled={vLoading}>
                            <Trash2 size={10}/> Prune old
                          </button>
                          <button className="ghost" style={{fontSize:'9px',padding:'3px 8px'}} onClick={async()=>{ await req('/vision/history/clear', {method:'POST'}); setVHistory([]); }} disabled={vLoading}>
                            Clear
                          </button>
                        </div>
                      </div>

                      <div style={{maxHeight:'280px',overflowY:'auto'}}>
                        {vHistory.map((h: any, idx: number) => (
                          <div key={idx} className="desktop-history-item">
                            <div>
                              <b style={{fontSize:'10px',color:'#f1f5f9'}}>{h.active_application || 'Windows'}</b>
                              <p style={{margin:'2px 0 0',fontSize:'9px',color:'#78869c',maxWidth:'240px',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>
                                {h.summary}
                              </p>
                              <small style={{fontSize:'8px',color:'#55637a'}}>
                                {h.timestamp?.slice(11, 19)} · {h.element_count} elements · {h.provider_used}
                              </small>
                            </div>
                          </div>
                        ))}
                        {!vHistory.length && (
                          <p style={{fontSize:'10px',color:'#64748b',textAlign:'center',padding:'30px 0'}}>
                            No visual analysis history yet.
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </>}

          {page === 'Files' && <>
            <Heading
              tag="PHASE 6 QUEUE 3"
              title="Advanced File Intelligence"
              desc="Intelligent document comprehension, FTS5 semantic search, spreadsheet analytics, and safe file organization."
              action={
                <div style={{display:'flex',gap:'8px'}}>
                  <button className="secondary" onClick={() => loadIndexStatusAction()} disabled={fIdxLoading}>
                    <RefreshCw size={14}/> Refresh Index
                  </button>
                </div>
              }
            />

            {/* Sub-tab navigation bar */}
            <div className="vision-tab-bar" style={{marginBottom:'16px'}}>
              <button className={`vision-tab-btn ${fTab === 'search' ? 'active' : ''}`} onClick={() => setFTab('search')}>
                <Search size={13}/> Semantic Search
              </button>
              <button className={`vision-tab-btn ${fTab === 'document' ? 'active' : ''}`} onClick={() => setFTab('document')}>
                <FileText size={13}/> Document Comprehension
              </button>
              <button className={`vision-tab-btn ${fTab === 'spreadsheet' ? 'active' : ''}`} onClick={() => setFTab('spreadsheet')}>
                <Table size={13}/> Spreadsheet Analytics
              </button>
              <button className={`vision-tab-btn ${fTab === 'compare' ? 'active' : ''}`} onClick={() => setFTab('compare')}>
                <Copy size={13}/> Compare Documents
              </button>
              <button className={`vision-tab-btn ${fTab === 'organize' ? 'active' : ''}`} onClick={() => setFTab('organize')}>
                <Folder size={13}/> Duplicates & Organization
              </button>
              <button className={`vision-tab-btn ${fTab === 'index' ? 'active' : ''}`} onClick={() => setFTab('index')}>
                <Boxes size={13}/> Index Management
              </button>
            </div>

            {/* Tab 1: Semantic Search */}
            {fTab === 'search' && (
              <div>
                <div className="panel" style={{marginBottom:'16px'}}>
                  <div style={{display:'flex',gap:'10px'}}>
                    <div style={{flex:1,position:'relative'}}>
                      <input
                        placeholder="Search document contents across PDF, DOCX, XLSX, PPTX, CSV, MD... (e.g. 'Computer Networks notes', 'budget expenses')"
                        value={fSearchQuery}
                        onChange={e => setFSearchQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && searchFilesAction()}
                      />
                    </div>
                    <select
                      style={{width:'140px'}}
                      value={fSearchFormat}
                      onChange={e => setFSearchFormat(e.target.value)}
                    >
                      <option value="all">All Formats</option>
                      <option value="pdf">PDF only</option>
                      <option value="docx">Word (.docx)</option>
                      <option value="xlsx">Excel (.xlsx)</option>
                      <option value="pptx">PowerPoint (.pptx)</option>
                      <option value="csv">CSV files</option>
                      <option value="md">Markdown (.md)</option>
                    </select>
                    <button className="primary" onClick={searchFilesAction} disabled={fSearchLoading}>
                      <Search size={14}/> {fSearchLoading ? 'Searching...' : 'Search'}
                    </button>
                  </div>

                  <div className="files-format-bar">
                    <span style={{fontSize:'9px',color:'#78869c',alignSelf:'center'}}>Supported formats:</span>
                    {['PDF','DOCX','DOC','TXT','MD','CSV','XLSX','XLS','PPTX','PPT','JSON','XML','HTML','RTF'].map(fmt => (
                      <span key={fmt} className="files-format-pill">{fmt}</span>
                    ))}
                  </div>
                </div>

                <div className="panel">
                  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'12px'}}>
                    <h3 style={{margin:0}}>Search Results ({fSearchResults.length})</h3>
                    <small>BM25 ranking with verified citations</small>
                  </div>

                  {fSearchResults.map((res: any, idx: number) => (
                    <div key={idx} className="files-search-result">
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                        <b>{res.filename}</b>
                        <div>
                          <span className="files-tag">{res.format.toUpperCase()}</span>
                          {res.page_number && <span className="files-tag">Page {res.page_number}</span>}
                          {res.sheet_name && <span className="files-tag">Sheet: {res.sheet_name}</span>}
                          {res.slide_number && <span className="files-tag">Slide {res.slide_number}</span>}
                        </div>
                      </div>
                      <small style={{color:'#64748b',fontSize:'9px'}}>{res.path}</small>
                      {res.section_title && (
                        <small style={{display:'block',color:'#a5b4fc',fontSize:'9px',marginTop:'3px'}}>
                          Section: {res.section_title}
                        </small>
                      )}
                      <p dangerouslySetInnerHTML={{ __html: res.snippet }}/>
                      <div style={{display:'flex',justifyContent:'flex-end',gap:'6px',marginTop:'6px'}}>
                        <button
                          className="ghost"
                          style={{fontSize:'9px',padding:'2px 8px'}}
                          onClick={() => { setFDocPath(res.path); setFTab('document'); }}
                        >
                          Open in Reader →
                        </button>
                      </div>
                    </div>
                  ))}

                  {!fSearchResults.length && !fSearchLoading && (
                    <p style={{fontSize:'11px',color:'#64748b',textAlign:'center',padding:'40px 0'}}>
                      No search results yet. Type a keyword above or refresh the index in Index Management.
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Tab 2: Document Comprehension */}
            {fTab === 'document' && (
              <div className="files-layout">
                <div>
                  <div className="panel" style={{marginBottom:'14px'}}>
                    <label>DOCUMENT PATH OR FILENAME</label>
                    <div style={{display:'flex',gap:'8px',marginTop:'6px'}}>
                      <input
                        placeholder="e.g. Downloads/report.pdf or Documents/notes.docx"
                        value={fDocPath}
                        onChange={e => setFDocPath(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && extractDocAction()}
                      />
                      <button className="primary" onClick={extractDocAction} disabled={fDocLoading}>
                        <FileText size={14}/> {fDocLoading ? 'Extracting...' : 'Extract'}
                      </button>
                      <button className="secondary" onClick={summarizeDocAction} disabled={fDocLoading}>
                        <Sparkles size={14}/> Summarize
                      </button>
                    </div>
                  </div>

                  {/* Document metadata strip */}
                  {fDocParsed && (
                    <div className="panel" style={{marginBottom:'14px'}}>
                      <div className="files-meta-strip">
                        <div>Format: <b>{fDocParsed.format.toUpperCase()}</b></div>
                        <div>Size: <b>{fDocParsed.metadata.size_formatted}</b></div>
                        <div>Words: <b>{fDocParsed.metadata.word_count}</b></div>
                        {fDocParsed.metadata.page_count > 0 && <div>Pages: <b>{fDocParsed.metadata.page_count}</b></div>}
                        {fDocParsed.metadata.sheet_count > 0 && <div>Sheets: <b>{fDocParsed.metadata.sheet_count}</b></div>}
                        {fDocParsed.metadata.slide_count > 0 && <div>Slides: <b>{fDocParsed.metadata.slide_count}</b></div>}
                        {fDocParsed.is_scanned && <div style={{color:'#f59e0b'}}>Scanned: <b>YES (OCR Required)</b></div>}
                      </div>

                      <h4 style={{fontSize:'12px',margin:'10px 0 6px'}}>Document Sections ({fDocParsed.sections?.length || 0})</h4>
                      <div style={{maxHeight:'320px',overflowY:'auto'}}>
                        {fDocParsed.sections?.map((sec: any, idx: number) => (
                          <div key={idx} style={{borderBottom:'1px solid #1a2333',padding:'8px 0'}}>
                            <div style={{display:'flex',justifyContent:'space-between'}}>
                              <b style={{fontSize:'10px',color:'#93c5fd'}}>{sec.title || `Section ${idx + 1}`}</b>
                              <small style={{fontSize:'8px',color:'#64748b'}}>
                                {sec.page_number ? `Page ${sec.page_number}` : ''}
                                {sec.sheet_name ? `Sheet: ${sec.sheet_name}` : ''}
                                {sec.slide_number ? `Slide ${sec.slide_number}` : ''}
                              </small>
                            </div>
                            <p style={{fontSize:'10px',color:'#cbd5e1',margin:'4px 0 0',lineHeight:'1.5',whiteSpace:'pre-wrap'}}>
                              {sec.content.length > 300 ? sec.content.slice(0, 300) + '...' : sec.content}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Summary & Key Points */}
                  {fDocSummary && (
                    <div className="panel">
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                        <h4 style={{fontSize:'13px',margin:0}}>Extract-Based Summary</h4>
                        <span className="files-tag">{fDocSummary.classification?.category || 'Document'}</span>
                      </div>
                      <p style={{fontSize:'11px',color:'#e2e8f0',lineHeight:'1.6',margin:'8px 0'}}>
                        {fDocSummary.summary}
                      </p>
                      <h5 style={{fontSize:'10px',color:'#94a3b8',margin:'12px 0 6px'}}>Key Takeaways:</h5>
                      <ul style={{margin:0,paddingLeft:'18px',fontSize:'10px',color:'#cbd5e1'}}>
                        {fDocSummary.key_points?.map((pt: string, idx: number) => (
                          <li key={idx} style={{marginBottom:'4px'}}>{pt}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Right Column: Ask Document Interface */}
                <div>
                  <div className="panel">
                    <h3 style={{margin:'0 0 4px',fontSize:'13px'}}>Ask Document</h3>
                    <small>Grounded factual answers with exact citations</small>
                    <div style={{marginTop:'10px'}}>
                      <textarea
                        rows={3}
                        placeholder="Ask a question about the document... (e.g. 'What was the Q3 revenue?' or 'What are the system requirements?')"
                        value={fDocQuestion}
                        onChange={e => setFDocQuestion(e.target.value)}
                      />
                      <button
                        className="primary"
                        style={{width:'100%',marginTop:'8px'}}
                        onClick={askDocAction}
                        disabled={fDocLoading || !fDocPath.trim()}
                      >
                        <Sparkles size={14}/> {fDocLoading ? 'Searching Document...' : 'Ask Question'}
                      </button>
                    </div>

                    {fDocAnswer && (
                      <div style={{marginTop:'16px'}}>
                        <h5 style={{fontSize:'10px',color:'#94a3b8',margin:'0 0 6px'}}>Grounded Answer:</h5>
                        <p style={{fontSize:'11px',color:'#f1f5f9',lineHeight:'1.6',whiteSpace:'pre-wrap'}}>
                          {fDocAnswer.answer}
                        </p>

                        <h5 style={{fontSize:'10px',color:'#94a3b8',margin:'12px 0 6px'}}>
                          Verified Source Citations ({fDocAnswer.citations?.length || 0}):
                        </h5>
                        {fDocAnswer.citations?.map((cit: any, idx: number) => (
                          <div key={idx} className="files-citation-card">
                            <small>
                              {cit.document_name}
                              {cit.page_number && ` · Page ${cit.page_number}`}
                              {cit.sheet_name && ` · Sheet: ${cit.sheet_name}`}
                              {cit.slide_number && ` · Slide ${cit.slide_number}`}
                            </small>
                            <span style={{color:'#e2e8f0'}}>"{cit.exact_quote}"</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Tab 3: Spreadsheet Analytics */}
            {fTab === 'spreadsheet' && (
              <div>
                <div className="panel" style={{marginBottom:'14px'}}>
                  <label>SPREADSHEET PATH (.XLSX OR .CSV)</label>
                  <div style={{display:'flex',gap:'8px',marginTop:'6px'}}>
                    <input
                      placeholder="e.g. Downloads/expenses.xlsx or data/report.csv"
                      value={fSsPath}
                      onChange={e => setFSsPath(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && profileSpreadsheetAction()}
                    />
                    <button className="primary" onClick={() => profileSpreadsheetAction()} disabled={fSsLoading}>
                      <Table size={14}/> {fSsLoading ? 'Analyzing...' : 'Analyze Spreadsheet'}
                    </button>
                  </div>
                </div>

                {fSsProfile && (
                  <div>
                    {/* Worksheet switcher */}
                    {fSsProfile.sheet_names?.length > 1 && (
                      <div className="vision-tab-bar" style={{marginBottom:'10px'}}>
                        {fSsProfile.sheet_names.map((sn: string) => (
                          <button
                            key={sn}
                            className={`vision-tab-btn ${fSsActiveSheet === sn ? 'active' : ''}`}
                            onClick={() => profileSpreadsheetAction(sn)}
                          >
                            Sheet: {sn}
                          </button>
                        ))}
                      </div>
                    )}

                    {/* Stats Strip */}
                    <div className="files-meta-strip">
                      <div>File: <b>{fSsProfile.filename}</b></div>
                      <div>Rows: <b>{fSsProfile.row_count}</b></div>
                      <div>Columns: <b>{fSsProfile.col_count}</b></div>
                      <div>Duplicate Rows: <b>{fSsProfile.duplicate_row_count}</b></div>
                      <div>Formulas: <b>{fSsProfile.formulas_detected?.length || 0}</b></div>
                    </div>

                    {/* Column Profiles */}
                    <div className="panel" style={{marginBottom:'14px'}}>
                      <h4 style={{fontSize:'12px',margin:'0 0 8px'}}>Column Schema & Statistics</h4>
                      <div className="files-table-wrapper">
                        <table className="files-table">
                          <thead>
                            <tr>
                              <th>Column</th>
                              <th>Type</th>
                              <th>Non-Null</th>
                              <th>Nulls</th>
                              <th>Distinct</th>
                              <th>Min</th>
                              <th>Max</th>
                              <th>Mean</th>
                              <th>Median</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fSsProfile.columns?.map((c: any, idx: number) => (
                              <tr key={idx}>
                                <td><b>{c.name}</b></td>
                                <td><span className="files-tag">{c.dtype}</span></td>
                                <td>{c.non_null_count}</td>
                                <td>{c.null_count}</td>
                                <td>{c.distinct_count}</td>
                                <td>{c.min_val ?? '—'}</td>
                                <td>{c.max_val ?? '—'}</td>
                                <td>{c.mean_val ?? '—'}</td>
                                <td>{c.median_val ?? '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* Interactive Filter / Sort & Data Table */}
                    <div className="panel">
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                        <h4 style={{fontSize:'12px',margin:0}}>Data Preview</h4>
                        <div style={{display:'flex',gap:'6px'}}>
                          <input
                            placeholder="Filter text..."
                            style={{width:'130px',padding:'4px 8px',fontSize:'9px'}}
                            value={fSsFilterVal}
                            onChange={e => setFSsFilterVal(e.target.value)}
                          />
                          <select
                            style={{width:'120px',padding:'4px 8px',fontSize:'9px'}}
                            value={fSsFilterCol}
                            onChange={e => setFSsFilterCol(e.target.value)}
                          >
                            <option value="">All Columns</option>
                            {fSsProfile.columns?.map((c: any) => (
                              <option key={c.name} value={c.name}>{c.name}</option>
                            ))}
                          </select>
                          <button className="secondary" style={{padding:'4px 8px',fontSize:'9px'}} onClick={querySpreadsheetAction}>
                            <Filter size={11}/> Filter
                          </button>
                        </div>
                      </div>

                      <div className="files-table-wrapper">
                        <table className="files-table">
                          <thead>
                            <tr>
                              {fSsProfile.columns?.map((c: any) => (
                                <th key={c.name}>{c.name}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {fSsProfile.preview_rows?.map((row: any, rIdx: number) => (
                              <tr key={rIdx}>
                                {fSsProfile.columns?.map((c: any) => (
                                  <td key={c.name}>{String(row[c.name] ?? '')}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Tab 4: Compare Documents */}
            {fTab === 'compare' && (
              <div>
                <div className="panel" style={{marginBottom:'14px'}}>
                  <div style={{display:'grid',gridTemplateColumns:'1fr 1fr auto',gap:'10px',alignItems:'end'}}>
                    <div>
                      <label>DOCUMENT A</label>
                      <input
                        placeholder="Path to Document A (e.g. v1.pdf)"
                        value={fCmpFileA}
                        onChange={e => setFCmpFileA(e.target.value)}
                      />
                    </div>
                    <div>
                      <label>DOCUMENT B</label>
                      <input
                        placeholder="Path to Document B (e.g. v2.pdf)"
                        value={fCmpFileB}
                        onChange={e => setFCmpFileB(e.target.value)}
                      />
                    </div>
                    <button className="primary" onClick={compareDocsAction} disabled={fCmpLoading}>
                      <Copy size={14}/> {fCmpLoading ? 'Comparing...' : 'Compare Documents'}
                    </button>
                  </div>
                </div>

                {fCmpResult && (
                  <div className="panel">
                    <h3 style={{fontSize:'13px',margin:'0 0 6px'}}>Document Comparison Results</h3>
                    <div className="files-meta-strip">
                      <div>Similarity: <b>{Math.round(fCmpResult.similarity_score * 100)}%</b></div>
                      <div>Common Sections: <b>{fCmpResult.common_sections?.length || 0}</b></div>
                      <div>Unique to A: <b>{fCmpResult.unique_to_a?.length || 0}</b></div>
                      <div>Unique to B: <b>{fCmpResult.unique_to_b?.length || 0}</b></div>
                    </div>

                    <p style={{fontSize:'11px',color:'#cbd5e1',lineHeight:'1.6',whiteSpace:'pre-wrap'}}>
                      {fCmpResult.summary_diff}
                    </p>

                    <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'14px',marginTop:'14px'}}>
                      <div className="panel" style={{background:'#0c1018'}}>
                        <h4 style={{fontSize:'11px',margin:'0 0 6px',color:'#93c5fd'}}>Unique to {fCmpResult.doc_a_name}:</h4>
                        <ul style={{margin:0,paddingLeft:'16px',fontSize:'10px',color:'#cbd5e1'}}>
                          {fCmpResult.unique_to_a?.map((s: string, idx: number) => (
                            <li key={idx}>{s}</li>
                          ))}
                          {!fCmpResult.unique_to_a?.length && <li>None</li>}
                        </ul>
                      </div>
                      <div className="panel" style={{background:'#0c1018'}}>
                        <h4 style={{fontSize:'11px',margin:'0 0 6px',color:'#a5b4fc'}}>Unique to {fCmpResult.doc_b_name}:</h4>
                        <ul style={{margin:0,paddingLeft:'16px',fontSize:'10px',color:'#cbd5e1'}}>
                          {fCmpResult.unique_to_b?.map((s: string, idx: number) => (
                            <li key={idx}>{s}</li>
                          ))}
                          {!fCmpResult.unique_to_b?.length && <li>None</li>}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Tab 5: Duplicates & File Organization */}
            {fTab === 'organize' && (
              <div>
                <div className="panel" style={{marginBottom:'14px'}}>
                  <label>SCAN DIRECTORY</label>
                  <div style={{display:'flex',gap:'8px',marginTop:'6px'}}>
                    <input
                      placeholder="e.g. Downloads or Documents"
                      value={fOrgFolder}
                      onChange={e => setFOrgFolder(e.target.value)}
                    />
                    <button className="primary" onClick={findDuplicatesAction} disabled={fOrgLoading}>
                      <Copy size={14}/> {fOrgLoading ? 'Scanning...' : 'Scan Duplicates'}
                    </button>
                    <button className="secondary" onClick={previewOrgAction} disabled={fOrgLoading}>
                      <Folder size={14}/> Organization Preview
                    </button>
                  </div>
                </div>

                {/* Duplicates view */}
                {fOrgDuplicates.length > 0 && (
                  <div className="panel" style={{marginBottom:'14px'}}>
                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'12px'}}>
                      <h4 style={{fontSize:'12px',margin:0}}>Exact Duplicate Files ({fOrgDuplicates.length} groups)</h4>
                      <small>Cryptographic SHA-256 verification</small>
                    </div>

                    {fOrgDuplicates.map((grp: any, idx: number) => (
                      <div key={idx} className="files-dup-card">
                        <div className="files-dup-header">
                          <span style={{fontSize:'9px',color:'#94a3b8',fontFamily:'monospace'}}>
                            SHA: {grp.sha256.slice(0, 16)}...
                          </span>
                          <span className="files-dup-wasted">Wasted: {grp.wasted_formatted}</span>
                        </div>
                        {grp.files?.map((f: any, fIdx: number) => (
                          <div key={fIdx} style={{display:'flex',justifyContent:'space-between',padding:'4px 0',fontSize:'10px'}}>
                            <span style={{color: fIdx === 0 ? '#34d399' : '#cbd5e1'}}>
                              {fIdx === 0 ? '✓ Primary: ' : '• Duplicate: '} {f.path}
                            </span>
                            <small style={{color:'#64748b'}}>{f.modified_at?.slice(0, 10)}</small>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}

                {/* Organization Preview */}
                {fOrgPreview && (
                  <div className="panel">
                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'10px'}}>
                      <div>
                        <h4 style={{fontSize:'12px',margin:0}}>Proposed File Organization Actions</h4>
                        <small>Total scanned: {fOrgPreview.total_scanned} files</small>
                      </div>
                      <button
                        className="primary"
                        onClick={executeOrgAction}
                        disabled={fOrgLoading || !fOrgPreview.proposed_actions?.length}
                      >
                        <FileCheck size={14}/> Execute Reorganization (Approval)
                      </button>
                    </div>

                    {fOrgPreview.proposed_actions?.map((act: any, idx: number) => (
                      <div key={idx} className="files-action-row">
                        <div>
                          <b>{act.filename}</b>
                          <small style={{display:'block',color:'#818cf8'}}>{act.reason}</small>
                          <small style={{color:'#64748b'}}>{act.path}</small>
                        </div>
                        <div style={{textAlign:'right'}}>
                          <span className="files-tag">{act.suggested_action}</span>
                          {act.target_path && (
                            <small style={{display:'block',color:'#34d399'}}>→ {act.target_path}</small>
                          )}
                        </div>
                      </div>
                    ))}

                    {!fOrgPreview.proposed_actions?.length && (
                      <p style={{fontSize:'10px',color:'#64748b',textAlign:'center',padding:'20px 0'}}>
                        No cleanup or categorization actions needed in this directory.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Tab 6: Index Management */}
            {fTab === 'index' && (
              <div className="panel">
                <h3 style={{fontSize:'13px',margin:'0 0 6px'}}>Document Index Management</h3>
                <small>SQLite FTS5 full-text search database</small>

                {fIdxStatus && (
                  <div className="files-meta-strip" style={{marginTop:'12px'}}>
                    <div>Total Documents: <b>{fIdxStatus.total_documents}</b></div>
                    <div>Total Chunks: <b>{fIdxStatus.total_chunks}</b></div>
                    <div>Storage Size: <b>{fIdxStatus.index_storage_mb} MB</b></div>
                    <div>Last Indexed: <b>{fIdxStatus.last_indexed_at?.slice(0, 19) || 'Never'}</b></div>
                  </div>
                )}

                <div style={{marginTop:'16px'}}>
                  <label>INDEX FOLDER (INCREMENTAL)</label>
                  <div style={{display:'flex',gap:'8px',marginTop:'6px'}}>
                    <input
                      placeholder="Folder path to index (e.g. Downloads, Documents)"
                      value={fIdxFolder}
                      onChange={e => setFIdxFolder(e.target.value)}
                    />
                    <button className="primary" onClick={refreshIndexAction} disabled={fIdxLoading}>
                      <RefreshCw size={14}/> {fIdxLoading ? 'Indexing...' : 'Index Folder'}
                    </button>
                    <button
                      className="secondary"
                      onClick={async () => {
                        await req('/files/index/clear', { method: 'POST' });
                        Z('Document index cleared.');
                        loadIndexStatusAction();
                      }}
                      disabled={fIdxLoading}
                    >
                      <Trash2 size={14}/> Clear Index
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>}

          {page === 'Assistant' && <>
            <Heading
              tag="PHASE 6 QUEUE 4"
              title="Proactive Personal Assistance"
              desc="Autonomous daily briefings, intelligent deadline reminders, continuous system monitoring, and personalized task synthesis."
              action={
                <div style={{display:'flex',gap:'8px'}}>
                  <button className="primary" onClick={loadAssistantData} disabled={asBriefingLoading}>
                    <RefreshCw size={14}/> {asBriefingLoading ? 'Refreshing...' : 'Refresh Assistant'}
                  </button>
                </div>
              }
            />

            {/* Sub-tab navigation */}
            <div className="vision-tab-bar" style={{marginBottom:'16px'}}>
              <button className={`vision-tab-btn ${asTab === 'briefing' ? 'active' : ''}`} onClick={() => setAsTab('briefing')}>
                <Sparkles size={13}/> Daily Briefing
              </button>
              <button className={`vision-tab-btn ${asTab === 'reminders' ? 'active' : ''}`} onClick={() => setAsTab('reminders')}>
                <Calendar size={13}/> Reminders ({asReminders.filter(r => r.status === 'pending' || r.status === 'snoozed').length})
              </button>
              <button className={`vision-tab-btn ${asTab === 'monitors' ? 'active' : ''}`} onClick={() => setAsTab('monitors')}>
                <Shield size={13}/> Monitors ({asMonitors.filter(m => m.enabled).length})
              </button>
              <button className={`vision-tab-btn ${asTab === 'plan' ? 'active' : ''}`} onClick={() => setAsTab('plan')}>
                <Workflow size={13}/> Daily Plan
              </button>
              <button className={`vision-tab-btn ${asTab === 'profile' ? 'active' : ''}`} onClick={() => setAsTab('profile')}>
                <User size={13}/> Profile & Preferences
              </button>
              <button className={`vision-tab-btn ${asTab === 'notifications' ? 'active' : ''}`} onClick={() => setAsTab('notifications')}>
                <Bell size={13}/> Notifications {asUnreadCount > 0 && <span className="notif-badge">{asUnreadCount}</span>}
              </button>
            </div>

            {/* TAB 1: BRIEFING */}
            {asTab === 'briefing' && (
              <div className="as-layout">
                {asBriefing && (
                  <div className="as-briefing-hero">
                    <div className="as-greeting">{asBriefing.greeting}</div>
                    <div className="as-summary">{asBriefing.summary}</div>
                    
                    <div style={{marginTop:'16px',fontWeight:700,fontSize:'12px',color:'#f1f5f9'}}>
                      Actionable Next Steps
                    </div>
                    <div className="as-steps-grid">
                      {asBriefing.actionable_next_steps?.map((st: string, idx: number) => (
                        <div key={idx} className="as-step-card">
                          <ChevronRight size={14} color="#60a5fa" style={{flexShrink:0,marginTop:'2px'}}/>
                          <div>{st}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Quick Natural Task Creation */}
                <div className="box" style={{padding:'16px'}}>
                  <h4><Plus size={14}/> Natural Language Task Quick-Add</h4>
                  <div style={{display:'flex',gap:'8px',marginTop:'10px'}}>
                    <input
                      style={{flex:1}}
                      placeholder="e.g. 'Review quarterly budget and finish by 5pm tomorrow #finance' or 'Fix auth bug asap'"
                      value={natTaskInput}
                      onChange={e => setNatTaskInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') createNaturalTaskAction(); }}
                    />
                    <select value={natTaskPriority} onChange={e => setNatTaskPriority(e.target.value)} style={{width:'130px'}}>
                      <option value="">Auto-Priority</option>
                      <option value="critical">Critical</option>
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                    </select>
                    <button className="primary" onClick={createNaturalTaskAction}>Add Task</button>
                  </div>
                </div>

                {/* Overview Cards: Overdue & Upcoming */}
                <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'16px',marginTop:'14px'}}>
                  <div className="box" style={{padding:'14px'}}>
                    <h4 style={{display:'flex',alignItems:'center',gap:'6px',color:'#f87171'}}>
                      <AlertTriangle size={15}/> Overdue Tasks ({asBriefing?.overdue_tasks?.length || 0})
                    </h4>
                    {asBriefing?.overdue_tasks?.length === 0 ? (
                      <p style={{fontSize:'11px',color:'#64748b',marginTop:'8px'}}>No overdue tasks. All clear!</p>
                    ) : (
                      asBriefing?.overdue_tasks?.map((t: any) => (
                        <div key={t.id} style={{padding:'8px 0',borderTop:'1px solid #1e293b',fontSize:'11px'}}>
                          <b>{t.title}</b>
                          <div style={{color:'#94a3b8',fontSize:'10px',marginTop:'2px'}}>
                            Due: <span style={{color:'#f87171'}}>{t.deadline}</span> · Priority: {t.priority}
                          </div>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="box" style={{padding:'14px'}}>
                    <h4 style={{display:'flex',alignItems:'center',gap:'6px',color:'#60a5fa'}}>
                      <Clock3 size={15}/> Upcoming Deadlines (Next 72h) ({asBriefing?.upcoming_deadlines?.length || 0})
                    </h4>
                    {asBriefing?.upcoming_deadlines?.length === 0 ? (
                      <p style={{fontSize:'11px',color:'#64748b',marginTop:'8px'}}>No imminent deadlines approaching in the next 72 hours.</p>
                    ) : (
                      asBriefing?.upcoming_deadlines?.map((t: any) => (
                        <div key={t.id} style={{padding:'8px 0',borderTop:'1px solid #1e293b',fontSize:'11px'}}>
                          <b>{t.title}</b>
                          <div style={{color:'#94a3b8',fontSize:'10px',marginTop:'2px'}}>
                            Due: <span style={{color:'#60a5fa'}}>{t.deadline}</span> · Priority: {t.priority}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: REMINDERS */}
            {asTab === 'reminders' && (
              <div>
                <div className="box" style={{padding:'16px',marginBottom:'16px'}}>
                  <h4><Plus size={14}/> Schedule New Intelligent Reminder</h4>
                  <div style={{display:'grid',gridTemplateColumns:'2fr 1.5fr 1fr auto',gap:'10px',marginTop:'10px'}}>
                    <input
                      placeholder="Reminder title (e.g. Weekly project sync)"
                      value={remTitle}
                      onChange={e => setRemTitle(e.target.value)}
                    />
                    <input
                      type="datetime-local"
                      value={remDueAt}
                      onChange={e => setRemDueAt(e.target.value)}
                    />
                    <select value={remType} onChange={e => setRemType(e.target.value)}>
                      <option value="one_time">One-time</option>
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                      <option value="deadline">Deadline</option>
                      <option value="follow_up">Follow-up</option>
                    </select>
                    <button className="primary" onClick={createReminderAction}>Set Reminder</button>
                  </div>
                </div>

                <div>
                  {asReminders.length === 0 ? (
                    <div className="box" style={{padding:'20px',textAlign:'center',color:'#64748b'}}>
                      No reminders scheduled. Use the form above to add one.
                    </div>
                  ) : (
                    asReminders.map((r: any) => (
                      <div key={r.id} className="as-rem-card">
                        <div className="as-rem-info">
                          <div className="as-rem-title">{r.title}</div>
                          <div className="as-rem-meta">
                            <span className={`as-pill ${r.status}`}>{r.status}</span>
                            <span>Type: <b>{r.reminder_type}</b></span>
                            <span>Due: <b>{r.due_at}</b></span>
                            {r.snoozed_until && <span>Snoozed until: <b>{r.snoozed_until}</b></span>}
                          </div>
                        </div>
                        <div style={{display:'flex',gap:'6px'}}>
                          {(r.status === 'pending' || r.status === 'snoozed') && (
                            <>
                              <button className="secondary" style={{padding:'4px 8px',fontSize:'10px'}} onClick={() => snoozeReminder(r.id, 15)}>
                                +15m
                              </button>
                              <button className="secondary" style={{padding:'4px 8px',fontSize:'10px'}} onClick={() => snoozeReminder(r.id, 60)}>
                                +1h
                              </button>
                            </>
                          )}
                          {r.status !== 'dismissed' && (
                            <button className="ghost" style={{padding:'4px 8px',fontSize:'10px'}} onClick={() => dismissReminder(r.id)}>
                              Dismiss
                            </button>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* TAB 3: MONITORS */}
            {asTab === 'monitors' && (
              <div>
                <div className="box" style={{padding:'16px',marginBottom:'16px'}}>
                  <h4><Plus size={14}/> Add Continuous Proactive Monitor</h4>
                  <div style={{display:'grid',gridTemplateColumns:'1.5fr 1.5fr 1fr 1fr auto',gap:'10px',marginTop:'10px'}}>
                    <input
                      placeholder="Monitor name (e.g. Watch Overdue Tasks)"
                      value={monName}
                      onChange={e => setMonName(e.target.value)}
                    />
                    <select value={monType} onChange={e => setMonType(e.target.value)}>
                      <option value="task_overdue">Task Overdue</option>
                      <option value="scheduler_failure">Scheduler Failure Alert</option>
                      <option value="pending_approval">Pending Approval Age</option>
                      <option value="file_change">File Change Watch</option>
                      <option value="recurring_due">Recurring Automation Health</option>
                    </select>
                    <input
                      placeholder="Target path or *"
                      value={monTarget}
                      onChange={e => setMonTarget(e.target.value)}
                    />
                    <input
                      type="number"
                      placeholder="Threshold (sec)"
                      value={monThreshold}
                      onChange={e => setMonThreshold(Number(e.target.value))}
                    />
                    <button className="primary" onClick={createMonitorAction}>Create Monitor</button>
                  </div>
                </div>

                <div>
                  {asMonitors.map((m: any) => (
                    <div key={m.id} className="as-mon-card">
                      <div>
                        <div style={{fontSize:'12px',fontWeight:600,color:'#f1f5f9'}}>{m.name}</div>
                        <div style={{fontSize:'10px',color:'#94a3b8',marginTop:'3px',display:'flex',gap:'10px'}}>
                          <span>Type: <b>{m.monitor_type}</b></span>
                          <span>Target: <b>{m.target_identifier}</b></span>
                          <span>Threshold: <b>{m.threshold_seconds}s</b></span>
                          {m.last_alert_at && <span style={{color:'#fbbf24'}}>Last Alert: {m.last_alert_at}</span>}
                        </div>
                      </div>
                      <div style={{display:'flex',gap:'8px',alignItems:'center'}}>
                        <button
                          className={m.enabled ? 'primary' : 'secondary'}
                          style={{padding:'4px 10px',fontSize:'10px'}}
                          onClick={() => toggleMonitor(m.id, !m.enabled)}
                        >
                          {m.enabled ? 'Enabled' : 'Paused'}
                        </button>
                        <button className="ghost" style={{padding:'4px 8px'}} onClick={() => deleteMonitor(m.id)}>
                          <Trash2 size={13}/>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* TAB 4: DAILY PLAN */}
            {asTab === 'plan' && (
              <div className="as-layout">
                {asDailyPlan && (
                  <>
                    <div className="box" style={{padding:'16px'}}>
                      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                        <div>
                          <h4 style={{margin:0}}>Optimized Schedule for {asDailyPlan.date}</h4>
                          <small style={{color:'#94a3b8'}}>{asDailyPlan.total_tasks} tasks scheduled · Total estimated workload: {asDailyPlan.total_estimated_hours} hours</small>
                        </div>
                      </div>

                      {asDailyPlan.conflicts && asDailyPlan.conflicts.length > 0 && (
                        <div style={{background:'rgba(239,68,68,0.1)',border:'1px solid #ef4444',borderRadius:'6px',padding:'10px 14px',marginTop:'12px'}}>
                          <b style={{color:'#ef4444',fontSize:'11px',display:'flex',alignItems:'center',gap:'6px'}}>
                            <AlertTriangle size={14}/> Schedule Conflicts Detected ({asDailyPlan.conflicts.length})
                          </b>
                          {asDailyPlan.conflicts.map((cf: any, idx: number) => (
                            <div key={idx} style={{fontSize:'10px',color:'#fca5a5',marginTop:'3px'}}>
                              • {cf.title || cf.date}: {cf.details}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="box" style={{padding:'16px'}}>
                      <h4 style={{marginBottom:'10px'}}>Sequenced Daily Execution Plan</h4>
                      <div className="files-table-wrapper">
                        <table className="files-table">
                          <thead>
                            <tr>
                              <th>Seq</th>
                              <th>Task Title</th>
                              <th>Priority</th>
                              <th>Project</th>
                              <th>Est. Duration</th>
                              <th>Cumulative Time</th>
                              <th>Deadline</th>
                            </tr>
                          </thead>
                          <tbody>
                            {asDailyPlan.plan?.map((t: any, idx: number) => (
                              <tr key={t.id}>
                                <td>#{idx + 1}</td>
                                <td><b>{t.title}</b></td>
                                <td>
                                  <span className={`as-pill ${t.priority === 'critical' ? 'missed' : t.priority === 'high' ? 'snoozed' : 'pending'}`}>
                                    {t.priority}
                                  </span>
                                </td>
                                <td>{t.project}</td>
                                <td>{t.duration_minutes} mins</td>
                                <td>{Math.round(t.cumulative_minutes / 60 * 10) / 10} hrs</td>
                                <td>{t.deadline || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* TAB 5: PROFILE & PREFERENCES */}
            {asTab === 'profile' && (
              <div>
                <div className="as-profile-grid">
                  {/* Working Hours */}
                  <div className="as-profile-card">
                    <h4><Clock3 size={14}/> Working Hours & Availability</h4>
                    <div style={{fontSize:'11px',color:'#94a3b8',lineHeight:'1.8'}}>
                      <div>Daily Window: <b style={{color:'#f1f5f9'}}>{asProfile?.working_hours?.start_time || '09:00'} – {asProfile?.working_hours?.end_time || '18:00'}</b></div>
                      <div>Timezone: <b style={{color:'#f1f5f9'}}>{asProfile?.working_hours?.timezone || 'Local'}</b></div>
                      <div>Active Work Days: <b style={{color:'#f1f5f9'}}>Monday – Friday</b></div>
                    </div>
                  </div>

                  {/* Goals & Projects */}
                  <div className="as-profile-card">
                    <h4><Workflow size={14}/> Ongoing Projects & Goals</h4>
                    <div style={{fontSize:'11px',color:'#94a3b8'}}>
                      <div>Projects: <b style={{color:'#60a5fa'}}>{asProfile?.projects?.map((p: any) => typeof p === 'string' ? p : p.name).join(', ') || 'General'}</b></div>
                      <div style={{marginTop:'4px'}}>Communication: <b style={{color:'#34d399'}}>{asProfile?.communication_style || 'concise'}</b></div>
                    </div>
                  </div>
                </div>

                {/* Add Preference */}
                <div className="box" style={{padding:'14px',margin:'14px 0'}}>
                  <h4><Plus size={14}/> Add Profile Preference / Goal</h4>
                  <div style={{display:'grid',gridTemplateColumns:'1.5fr 2fr 1fr auto',gap:'10px',marginTop:'8px'}}>
                    <input placeholder="Key (e.g. preferred_editor)" value={newPrefKey} onChange={e => setNewPrefKey(e.target.value)}/>
                    <input placeholder="Value (e.g. VS Code)" value={newPrefVal} onChange={e => setNewPrefVal(e.target.value)}/>
                    <select value={newPrefCat} onChange={e => setNewPrefCat(e.target.value)}>
                      <option value="preferences">Preferences</option>
                      <option value="goals">Goals</option>
                      <option value="projects">Projects</option>
                      <option value="routines">Routines</option>
                    </select>
                    <button className="primary" onClick={createProfileItem}>Save Item</button>
                  </div>
                </div>

                {/* Profile Items Table */}
                <div className="box" style={{padding:'14px'}}>
                  <h4>Stored Profile Items & Confidence Level</h4>
                  <small style={{color:'#94a3b8'}}>Strict distinction between user-confirmed facts and assistant-inferred preferences. Credentials and API keys are blocked.</small>
                  <div className="files-table-wrapper" style={{marginTop:'10px'}}>
                    <table className="files-table">
                      <thead>
                        <tr>
                          <th>Key</th>
                          <th>Value</th>
                          <th>Category</th>
                          <th>Confirmation Status</th>
                          <th>Source</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {asProfile?.items?.map((it: any) => (
                          <tr key={it.key}>
                            <td><b>{it.key}</b></td>
                            <td>{typeof it.value === 'object' ? JSON.stringify(it.value) : String(it.value)}</td>
                            <td>{it.category}</td>
                            <td>
                              <span className={`as-pill ${it.is_confirmed ? 'confirmed' : 'inferred'}`}>
                                {it.is_confirmed ? 'Confirmed Fact' : 'Inferred Preference'}
                              </span>
                            </td>
                            <td>{it.source}</td>
                            <td>
                              {!it.is_confirmed && (
                                <button
                                  className="secondary"
                                  style={{padding:'2px 6px',fontSize:'9px'}}
                                  onClick={() => confirmProfileItem(it.key, it.value, it.category)}
                                >
                                  Confirm
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 6: NOTIFICATIONS */}
            {asTab === 'notifications' && (
              <div>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'12px'}}>
                  <h4>Persistent Notification Center ({asNotifications.length})</h4>
                  <small style={{color:'#94a3b8'}}>{asUnreadCount} unread alert(s)</small>
                </div>

                {asNotifications.length === 0 ? (
                  <div className="box" style={{padding:'20px',textAlign:'center',color:'#64748b'}}>
                    No notifications recorded.
                  </div>
                ) : (
                  asNotifications.map((n: any) => (
                    <div key={n.id} className={`as-notif-card ${n.severity} ${n.read_status ? 'read' : ''}`}>
                      <div>
                        <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
                          <span className={`as-pill ${n.severity}`}>{n.severity}</span>
                          <b style={{fontSize:'12px',color:'#f1f5f9'}}>{n.title}</b>
                          <small style={{fontSize:'10px',color:'#64748b'}}>{n.created_at}</small>
                        </div>
                        <p style={{fontSize:'11px',color:'#cbd5e1',margin:'4px 0 0 0'}}>{n.message}</p>
                      </div>
                      <div style={{display:'flex',gap:'6px'}}>
                        <button className="ghost" style={{padding:'4px 8px',fontSize:'10px'}} onClick={() => dismissNotification(n.id)}>
                          Dismiss
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </>}

          {!['Overview','Assistant','Chat','Tool Registry','Models','Settings','Activity Log','Browser','Tasks','Memory','Desktop','Visual AI','Files'].includes(page)&&(
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
