import { useState, useRef, useEffect } from 'react';
import {
  Send, Bot, User, Loader2, RefreshCw, Search, Sparkles,
  Zap, Layers, X, History, Eye, EyeOff, Star, Trash2, Archive, Mail
} from 'lucide-react';
import { useAuth } from '../AuthContext';
import { getActiveSender } from '../api';
import {
  queryEmailInsights, indexEmails, getRecentEmails,
  getEmailByUid, emailAction, getChatHistory,
  addChatTurn, searchEmails, getAiAgentStatus, refreshEmailCache,
} from '../api';
import type { ChatMessage, EmailSnippet } from '../types';
import { motion, AnimatePresence } from 'framer-motion';

const AiAgentPage: React.FC = () => {
  const { user } = useAuth();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messageEmails, setMessageEmails] = useState<(EmailSnippet[] | undefined)[]>([]);
  const [emails, setEmails] = useState<EmailSnippet[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<{ uid: string; body: string } | null>(null);
  const [quickIndexing, setQuickIndexing] = useState(false);
  const [deepIndexing, setDeepIndexing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [semanticQuery, setSemanticQuery] = useState('');
  const [semanticHits, setSemanticHits] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);
  const [specificUid, setSpecificUid] = useState('');
  const [selectedAction, setSelectedAction] = useState('mark_read');
  const [actionLoading, setActionLoading] = useState(false);
  const [promptScanUnlimited] = useState(false);
  const [promptScanMax, setPromptScanMax] = useState(200);
  const [showHistory, setShowHistory] = useState(false);
  const [chatHistory, setChatHistory] = useState<any[]>([]);
  const [refreshingCache, setRefreshingCache] = useState(false);
  const [deepScanning, setDeepScanning] = useState(false);
  const [activeSender, setActiveSender] = useState<{ name: string; email: string } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const actions = [
    { value: 'mark_read', label: 'Mark Read', icon: Eye },
    { value: 'mark_unread', label: 'Mark Unread', icon: EyeOff },
    { value: 'mark_important', label: 'Important', icon: Star },
    { value: 'move_to_trash', label: 'Trash', icon: Trash2 },
    { value: 'move_to_spam', label: 'Spam', icon: Archive },
  ];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadRecentEmails = async () => {
    try {
      const res = await getRecentEmails(500);
      setEmails(res.data.emails || []);
    } catch (e) { console.error(e); }
  };

  const loadChatHistory = async () => {
    if (!user) return;
    try {
      const res = await getChatHistory(user.id, 80);
      const history = res.data.history || [];
      setChatHistory(history);
      const loaded = history.map((h: any) => ({
        role: h.role as 'user' | 'assistant',
        content: h.content,
      }));
      setMessages(loaded);
      setMessageEmails(loaded.map(() => undefined));
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    loadRecentEmails();
    if (user) loadChatHistory();
  }, [user]);

  useEffect(() => {
    const fetchSender = async () => {
      try {
        const res = await getActiveSender();
        if (res.data && (res.data.name || res.data.email)) setActiveSender(res.data);
      } catch {}
    };
    fetchSender();
    const interval = setInterval(fetchSender, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleFastIndex = async () => {
    setQuickIndexing(true);
    try {
      const res = await indexEmails(400, 'headers');
      addAssistantMessage(`⚡ Fast index complete: ${res.data.indexed || 0} emails indexed!`);
    } catch (e) { console.error(e); } finally { setQuickIndexing(false); }
  };

  const handleDeepIndex = async () => {
    setDeepIndexing(true);
    try {
      const res = await indexEmails(250, 'full');
      addAssistantMessage(`🔬 Deep index complete: ${res.data.indexed || 0} emails indexed with full bodies!`);
    } catch (e) { console.error(e); } finally { setDeepIndexing(false); }
  };

  const handleSemanticSearch = async () => {
    if (!semanticQuery.trim()) return;
    setSearching(true);
    try {
      const res = await searchEmails(semanticQuery, 15);
      const hits = (res.data.hits || []);
      setSemanticHits(hits);
      addAssistantMessage(`🔍 Found ${hits.length} matching emails for "${semanticQuery}"`);
    } catch (e) { console.error(e); } finally { setSearching(false); }
  };

  const handleFetchFullEmail = async (uid: string) => {
    try {
      const res = await getEmailByUid(uid);
      if (res.data.body) {
        setSelectedEmail({ uid, body: res.data.body });
        addAssistantMessage(`📧 Fetched full email for UID ${uid}`);
      }
    } catch (e) { console.error(e); }
  };

  const handleAction = async () => {
    const uid = specificUid.trim();
    if (!uid) { addAssistantMessage('Please enter a UID to apply action'); return; }
    setActionLoading(true);
    try {
      const res = await emailAction(selectedAction, uid);
      addAssistantMessage(`✅ ${res.data.message || 'Action completed for UID ' + uid}`);
      await loadRecentEmails();
    } catch (e) { console.error(e); } finally { setActionLoading(false); }
  };

  const addAssistantMessage = (content: string, emails?: EmailSnippet[]) => {
    setMessages(prev => [...prev, { role: 'assistant', content }]);
    setMessageEmails(prev => [...prev, emails]);
  };

  const handleSend = async () => {
    if (!input.trim() || !user) return;

    try {
      const statusRes = await getAiAgentStatus();
      if (!statusRes.data.ready) {
        setMessages(prev => [...prev, { role: 'user', content: input }]);
        setMessageEmails(prev => [...prev, undefined]);
        addAssistantMessage(statusRes.data.message || 'No sender configured. Please add a sender in the Senders page.');
        return;
      }
    } catch (e) { /* continue */ }

    const userMessage = input;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setMessageEmails(prev => [...prev, undefined]);
    setLoading(true);

    try {
      const lowerMsg = userMessage.toLowerCase();
      if (lowerMsg.includes('open') || lowerMsg.includes('read') || lowerMsg.includes('show email')) {
        const uidMatch = userMessage.match(/uid[:\s]*(\d+)/i) || userMessage.match(/email\s*(\d+)/i);
        if (uidMatch) {
          const res = await getEmailByUid(uidMatch[1]);
          const body = res.data.body || 'No content';
          setMessages(prev => [...prev, { role: 'assistant', content: `Email UID ${uidMatch[1]}:\n\n${body}` }]);
          setMessageEmails(prev => [...prev, undefined]);
          setSelectedEmail({ uid: uidMatch[1], body });
          setLoading(false);
          return;
        }
      }

      const maxEmails = promptScanUnlimited ? 0 : promptScanMax;
      const res = await queryEmailInsights(userMessage, maxEmails, true);
      const answer = res.data.answer || 'No response';
      const returnedEmails: EmailSnippet[] = res.data.emails || [];
      setMessages(prev => [...prev, { role: 'assistant', content: answer }]);
      setMessageEmails(prev => [...prev, returnedEmails.length > 0 ? returnedEmails : undefined]);

      try { await addChatTurn(user.id, 'user', userMessage); await addChatTurn(user.id, 'assistant', answer); } catch (e) {}

      if (returnedEmails.length > 0) setEmails(returnedEmails);
    } catch (e: unknown) {
      let errorMsg = 'An unexpected error occurred';
      if (typeof e === 'object' && e !== null && 'response' in e) {
        const err = e as any;
        if (err.response?.data?.detail) errorMsg = err.response.data.detail;
      } else if (e instanceof Error) errorMsg = e.message;
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${errorMsg}` }]);
      setMessageEmails(prev => [...prev, undefined]);
    } finally { setLoading(false); }
  };

  return (
    <div className="flex h-[calc(100vh-4.5rem)] max-w-7xl mx-auto px-4 sm:px-6 gap-4 py-4">
      {/* Left Panel - Chat */}
      <div className="flex-1 flex flex-col glass-card rounded-2xl overflow-hidden">
        <div className="p-4 border-b border-slate-200/50 dark:border-slate-700/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent">AI Email Assistant</h1>
              <p className="text-xs text-slate-500">Ask me anything about your emails</p>
            </div>
            {activeSender && (
              <div className="ml-auto flex items-center gap-2 px-3 py-1.5 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg border border-emerald-200/50 dark:border-emerald-800/50">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400 truncate max-w-[150px]">
                  {activeSender.name || activeSender.email}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <AnimatePresence>
            {messages.length === 0 && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/30 dark:to-purple-900/30 flex items-center justify-center mb-4">
                  <Bot className="w-10 h-10 text-indigo-500" />
                </div>
                <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">Welcome to Email Assistant</h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md">Ask me to list emails, summarize your inbox, or perform actions like "mark email 123 as read"</p>
              </motion.div>
            )}
          </AnimatePresence>
          {messages.map((msg, idx) => (
            <motion.div key={idx} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * idx }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`flex gap-3 max-w-[80%] ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                  msg.role === 'user'
                    ? 'bg-gradient-to-br from-indigo-500 to-cyan-500 shadow-lg shadow-indigo-500/30'
                    : 'bg-gradient-to-br from-purple-500 to-pink-500 shadow-lg shadow-purple-500/30'
                }`}>
                  {msg.role === 'user' ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-white" />}
                </div>
                <div className={`px-4 py-3 rounded-2xl text-sm ${
                  msg.role === 'user'
                    ? 'bg-gradient-to-r from-indigo-500 to-purple-500 text-white'
                    : 'bg-slate-50 dark:bg-slate-800/50 border border-slate-200/50 dark:border-slate-700/50 text-slate-700 dark:text-slate-300'
                }`}>
                  <div className="whitespace-pre-wrap">
                    {msg.content.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
                      part.startsWith('**') && part.endsWith('**')
                        ? <strong key={i} className="text-indigo-600 dark:text-indigo-300">{part.slice(2, -2)}</strong>
                        : part
                    )}
                  </div>
                  {msg.role === 'assistant' && messageEmails[idx] && messageEmails[idx]!.length > 0 && (
                    <div className="mt-3 space-y-2 border-t border-slate-200 dark:border-slate-700 pt-3">
                      <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Referenced emails</p>
                      {messageEmails[idx]!.slice(0, 6).map((email) => (
                        <div key={email.uid} onClick={() => { setSelectedEmail({ uid: email.uid, body: email.body }); handleFetchFullEmail(email.uid); }}
                          className="p-2.5 bg-white dark:bg-slate-900 rounded-lg border border-slate-200/50 dark:border-slate-700/50 cursor-pointer hover:border-indigo-300 dark:hover:border-indigo-600 transition-all"
                        >
                          <div className="flex items-start justify-between gap-2 mb-1">
                            <p className="text-xs font-semibold text-slate-800 dark:text-slate-200 leading-snug line-clamp-1">
                              {email.subject || '(No subject)'}
                            </p>
                            <span className={`shrink-0 text-[9px] px-1.5 py-0.5 rounded-full font-medium ${email.seen ? 'bg-slate-100 dark:bg-slate-800 text-slate-400' : 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400'}`}>
                              {email.seen ? 'Read' : 'New'}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                            <span className="truncate max-w-[120px]">{email.from}</span>
                            <span>·</span>
                            <span className="shrink-0">{email.date?.split('T')[0]}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                  <Bot className="w-4 h-4 text-white" />
                </div>
                <div className="bg-slate-50 dark:bg-slate-800/50 border border-slate-200/50 dark:border-slate-700/50 rounded-2xl px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 text-purple-500 animate-spin" />
                    <span className="text-sm text-slate-500">Thinking...</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="px-4 py-2 border-t border-slate-200/50 dark:border-slate-700/50 bg-slate-50/50 dark:bg-slate-800/30">
          <div className="flex items-center gap-4 text-xs">
            <label className="flex items-center gap-2 cursor-pointer group">
              <div className={`w-10 h-5 rounded-full transition-colors ${promptScanUnlimited ? 'bg-indigo-500' : 'bg-slate-300 dark:bg-slate-600'}`}>
                <div className={`w-4 h-4 bg-white rounded-full shadow transform transition-transform ${promptScanUnlimited ? 'translate-x-5' : 'translate-x-0.5'} mt-0.5`} />
              </div>
              <span className="text-slate-500 group-hover:text-slate-700 dark:group-hover:text-slate-300 transition-colors">Unlimited scan</span>
            </label>
            {!promptScanUnlimited && (
              <div className="flex items-center gap-2">
                <span className="text-slate-400">Scan:</span>
                <input type="number" value={promptScanMax} onChange={(e) => setPromptScanMax(parseInt(e.target.value) || 200)}
                  className="w-16 px-2 py-1 text-xs border rounded-lg dark:bg-slate-700 dark:border-slate-600" min={20} max={1500} />
                <span className="text-slate-400">emails</span>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t border-slate-200/50 dark:border-slate-700/50">
          <div className="flex gap-3">
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())}
              placeholder="Ask about your emails or request actions..."
              className="flex-1 px-4 py-3 rounded-xl border border-slate-200/50 dark:border-slate-700/50 bg-white dark:bg-slate-900 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 transition-all outline-none dark:text-white" />
            <motion.button whileTap={{ scale: 0.95 }}
              onClick={handleSend} disabled={loading || !input.trim()}
              className="px-6 py-3 bg-gradient-to-r from-indigo-500 to-purple-500 text-white rounded-xl hover:from-indigo-600 hover:to-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-500/25 flex items-center gap-2 font-medium"
            >
              <Send className="w-4 h-4" />
              <span className="hidden sm:inline">Send</span>
            </motion.button>
          </div>
        </div>
      </div>

      {/* Right Panel - Tools */}
      <div className="w-80 lg:w-96 space-y-4 overflow-y-auto shrink-0">
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="p-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-indigo-500" />
              <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">Index & Search</span>
            </div>
          </div>
          <div className="p-3 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <button onClick={handleFastIndex} disabled={quickIndexing}
                className="flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-gradient-to-r from-emerald-500 to-teal-500 text-white rounded-lg hover:from-emerald-600 hover:to-teal-600 disabled:opacity-50 transition-all shadow-md"
              ><Zap className={`w-3 h-3 ${quickIndexing ? 'animate-spin' : ''}`} /> Fast</button>
              <button onClick={handleDeepIndex} disabled={deepIndexing}
                className="flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-lg hover:from-blue-600 hover:to-cyan-600 disabled:opacity-50 transition-all shadow-md"
              ><Layers className={`w-3 h-3 ${deepIndexing ? 'animate-spin' : ''}`} /> Deep</button>
            </div>

            <button onClick={async () => {
              setRefreshingCache(true);
              try { const res = await refreshEmailCache(); addAssistantMessage(res.data.message || 'Cache refreshed!'); } catch (e) { console.error(e); } finally { setRefreshingCache(false); }
            }} disabled={refreshingCache}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-rose-100 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400 rounded-lg hover:bg-rose-200 dark:hover:bg-rose-900/50 transition-all"
            ><RefreshCw className={`w-3 h-3 ${refreshingCache ? 'animate-spin' : ''}`} />Refresh Cache</button>

            <div className="space-y-2">
              <input type="text" value={semanticQuery} onChange={(e) => setSemanticQuery(e.target.value)}
                placeholder="Semantic search..." className="w-full px-3 py-2 text-sm border rounded-lg dark:bg-slate-700 dark:border-slate-600 outline-none"
                onKeyDown={(e) => e.key === 'Enter' && handleSemanticSearch()} />
              <button onClick={handleSemanticSearch} disabled={searching || !semanticQuery.trim()}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded-lg hover:bg-purple-200 dark:hover:bg-purple-900/50 transition-all"
              ><Search className={`w-3 h-3 ${searching ? 'animate-spin' : ''}`} /> Search</button>
            </div>

            {semanticHits.length > 0 && (
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {semanticHits.map((hit, idx) => (
                  <div key={idx} onClick={() => { setSpecificUid(hit.uid); handleFetchFullEmail(hit.uid); }}
                    className="px-2 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 rounded-lg cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors"
                  >UID {hit.uid} | {((hit.meta?.subject) || '(no subject)').substring(0, 30)}</div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="p-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-900/20 dark:to-orange-900/20">
            <div className="flex items-center gap-2">
              <Star className="w-4 h-4 text-amber-500" />
              <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">Actions</span>
            </div>
          </div>
          <div className="p-3 space-y-3">
            <div className="flex gap-2">
              <input type="text" value={specificUid} onChange={(e) => setSpecificUid(e.target.value)}
                placeholder="Enter UID" className="flex-1 px-3 py-2 text-sm border rounded-lg dark:bg-slate-700 dark:border-slate-600 outline-none" />
              <button onClick={() => specificUid && handleFetchFullEmail(specificUid)}
                className="px-3 py-2 text-xs bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors shrink-0">Fetch</button>
            </div>
            <select value={selectedAction} onChange={(e) => setSelectedAction(e.target.value)}
              className="w-full px-3 py-2 text-sm border rounded-lg dark:bg-slate-700 dark:border-slate-600 outline-none">
              {actions.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
            <button onClick={handleAction} disabled={actionLoading || !specificUid.trim()}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-gradient-to-r from-amber-500 to-orange-500 text-white rounded-lg hover:from-amber-600 hover:to-orange-600 disabled:opacity-50 transition-all"
            >{actionLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} Run Action</button>
          </div>
        </div>

        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="p-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-r from-rose-50 to-pink-50 dark:from-rose-900/20 dark:to-pink-900/20">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Mail className="w-4 h-4 text-rose-500" />
                <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">Inbox ({emails.length})</span>
              </div>
              <button onClick={async () => { setDeepScanning(true); try { const res = await getRecentEmails(500, true); setEmails(res.data.emails || []); } catch (e) { console.error(e); } finally { setDeepScanning(false); } }}
                className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors">
                <RefreshCw size={14} className={deepScanning ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>
          <div className="p-3 space-y-2">
            <div className="flex gap-2">
              <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search emails..." className="flex-1 px-3 py-2 text-xs border rounded-lg dark:bg-slate-700 dark:border-slate-600 outline-none"
                onKeyDown={async (e) => { if (e.key === 'Enter') { const res = await searchEmails(searchQuery, 20); const found = (res.data.hits || []).map((h: any) => ({ uid: h.uid, date: h.meta?.date || '', from: h.meta?.from || '', subject: h.meta?.subject || '(No subject)', body: '', seen: h.meta?.seen || false })); setEmails(found); } }} />
              <button className="p-2 bg-indigo-500 text-white rounded-lg hover:bg-indigo-600 transition-colors"><Search size={14} /></button>
            </div>
          </div>
          <div className="max-h-80 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-700/50">
            {emails.map((email) => (
              <div key={email.uid} onClick={() => { setSelectedEmail({ uid: email.uid, body: email.body }); handleFetchFullEmail(email.uid); }}
                className="p-3 cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors">
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${email.seen ? 'bg-slate-200 dark:bg-slate-700 text-slate-500' : 'bg-indigo-500 text-white'}`}>
                    {email.seen ? 'Read' : 'New'}
                  </span>
                  <span className="text-[10px] text-slate-400">{email.date?.split('T')[0]}</span>
                </div>
                <p className="text-xs font-medium truncate text-slate-800 dark:text-slate-200">{email.subject || '(No subject)'}</p>
                <p className="text-[10px] text-slate-500 truncate">{email.from}</p>
              </div>
            ))}
          </div>
        </div>

        <AnimatePresence>
          {selectedEmail && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              className="glass-card rounded-2xl overflow-hidden">
              <div className="p-3 border-b border-slate-200/50 dark:border-slate-700/50 bg-gradient-to-r from-cyan-50 to-blue-50 dark:from-cyan-900/20 dark:to-blue-900/20">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">UID: {selectedEmail.uid}</span>
                  <button onClick={() => setSelectedEmail(null)}
                    className="p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"><X size={14} /></button>
                </div>
              </div>
              <div className="p-3 max-h-64 overflow-y-auto">
                <pre className="text-xs whitespace-pre-wrap font-mono text-slate-700 dark:text-slate-300">{selectedEmail.body}</pre>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <button onClick={() => setShowHistory(!showHistory)}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-medium bg-slate-100 dark:bg-slate-800 rounded-xl hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-slate-600 dark:text-slate-400"
        ><History className="w-3 h-3" /> {showHistory ? 'Hide' : 'Show'} Chat History</button>

        <AnimatePresence>
          {showHistory && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}
              className="glass-card rounded-2xl p-3 space-y-2 max-h-64 overflow-y-auto">
              {chatHistory.slice(-20).map((turn, idx) => (
                <div key={idx} className="text-xs">
                  <span className="font-medium text-indigo-500">{turn.role === 'user' ? 'You' : 'AI'}: </span>
                  <span className="text-slate-500">{turn.content.substring(0, 100)}{turn.content.length > 100 ? '...' : ''}</span>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default AiAgentPage;
