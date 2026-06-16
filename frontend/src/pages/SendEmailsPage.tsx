import { useState, useEffect, useRef } from 'react';
import {
  FileText, Send, CheckCircle, X, StopCircle, Play,
  Sparkles, Zap, Eye, FileUp, AlertTriangle, UserCheck, Users,
  MailPlus, RefreshCw, Loader2, ArrowLeft, Paperclip
} from 'lucide-react';
import {
  uploadExcel, uploadAttachments, generateMessage, enhanceMessage, previewMessages,
  sendMessages, getSendStatus, stopSend, initManual,
  getActiveSender,
  sendSingleEmail, sendManualByIndex, listManual
} from '../api';
import SendProgress from '../components/SendProgress';
import ConnectGoogleButton from '../components/ConnectGoogleButton';
import { useAuth } from '../AuthContext';
import type { SendStatusResponse, ExcelUploadResponse, PreviewItem } from '../types';
import { motion, AnimatePresence } from 'framer-motion';

type Tab = 'bulk' | 'quick';

const SendEmailsPage: React.FC = () => {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>('bulk');
  const [activeStep, setActiveStep] = useState(0);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadData, setUploadData] = useState<ExcelUploadResponse | null>(null);
  const [objective, setObjective] = useState('');
  const [subject, setSubject] = useState('');
  const [messageTemplate, setMessageTemplate] = useState('');
  const [previews, setPreviews] = useState<PreviewItem[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<SendStatusResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [activeSender, setActiveSender] = useState<{ name: string; email: string } | null>(null);

  const [manualMode, setManualMode] = useState(false);
  const [manualContacts, setManualContacts] = useState<any[]>([]);
  const [manualCurrentIndex, setManualCurrentIndex] = useState(0);
  const [manualSubject, setManualSubject] = useState('');
  const [manualMessage, setManualMessage] = useState('');

  const [quickTo, setQuickTo] = useState('');
  const [quickSubject, setQuickSubject] = useState('');
  const [quickBody, setQuickBody] = useState('');
  const [quickSending, setQuickSending] = useState(false);
  const [quickSent, setQuickSent] = useState(false);

  useEffect(() => {
    loadStatus();
    loadActiveSender();
    const interval = setInterval(loadStatus, 2000);
    const senderInterval = setInterval(loadActiveSender, 5000);
    const onFocus = () => loadActiveSender();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) loadActiveSender(); });
    return () => {
      clearInterval(interval);
      clearInterval(senderInterval);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  useEffect(() => {
    if (manualContacts.length > 0 && manualContacts[manualCurrentIndex]) {
      const contact = manualContacts[manualCurrentIndex];
      setManualSubject(contact.subject || subject);
      setManualMessage(contact.body || messageTemplate);
    }
  }, [manualCurrentIndex, manualContacts]);

  const loadStatus = async () => {
    try {
      const res = await getSendStatus();
      setStatus(res.data);
    } catch (e) { console.error(e); }
  };

  const loadActiveSender = async () => {
    try {
      const res = await getActiveSender();
      setActiveSender(res.data.active ? res.data.sender : null);
    } catch { setActiveSender(null); }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedFile(file);
    setLoading(true);
    try {
      const res = await uploadExcel(file);
      setUploadData(res.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Upload failed');
    } finally { setLoading(false); }
  };

  const handleAttachFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newFiles = Array.from(files);
    setAttachments(prev => [...prev, ...newFiles]);
    try {
      await uploadAttachments(newFiles);
    } catch (err: any) {
      console.error('Failed to upload attachments', err);
    }
  };

  const handleGenerate = async () => {
    if (!objective) return;
    setLoading(true);
    try {
      const res = await generateMessage(objective);
      setMessageTemplate(res.data.message);
    } catch (err: any) { console.error(err); } finally { setLoading(false); }
  };

  const handleEnhance = async () => {
    if (!messageTemplate) return;
    setLoading(true);
    try {
      const res = await enhanceMessage(messageTemplate);
      setMessageTemplate(res.data.message);
    } catch (err: any) { console.error(err); } finally { setLoading(false); }
  };

  const handlePreview = async () => {
    if (!messageTemplate) return;
    setLoading(true);
    try {
      const res = await previewMessages(messageTemplate, 5);
      setPreviews(res.data.previews || []);
      setShowPreview(true);
    } catch (err: any) { console.error(err); } finally { setLoading(false); }
  };

  const handleSend = async () => {
    if (!subject || !messageTemplate) return;
    if (!uploadData) { alert('Please upload an Excel file first.'); return; }
    if (!activeSender) { alert('Please select an active sender first (Senders page).'); return; }
    setSending(true);
    try {
      const res = await sendMessages(subject, messageTemplate);
      setCurrentJobId(res.data.job_id);
      await loadStatus();
    } catch (err: any) { alert(err.response?.data?.detail || 'Send failed'); } finally { setSending(false); }
  };

  const handleInitManual = async () => {
    if (!subject || !messageTemplate) return;
    if (!uploadData) { alert('Please upload an Excel file first.'); return; }
    if (!activeSender) { alert('Please select an active sender first (Senders page).'); return; }
    setLoading(true);
    try {
      await initManual(subject, messageTemplate);
      const listRes = await listManual();
      setManualContacts(listRes.data.contacts || []);
    } catch (err: any) { alert(err.response?.data?.detail || 'Failed to initialize'); } finally { setLoading(false); }
  };

  const loadManualList = async () => {
    try {
      const res = await listManual();
      setManualContacts(res.data.contacts || []);
    } catch (e) { console.error(e); }
  };

  const handleSendByIndex = async (index: number, skip = false) => {
    setLoading(true);
    try {
      if (skip) {
        await sendManualByIndex(index, true);
      } else {
        await sendManualByIndex(index, false, manualSubject, manualMessage);
      }
      await loadManualList();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to send');
    } finally { setLoading(false); }
  };

  const handleEmergencyStop = async (jobId?: string) => {
    try {
      await stopSend(jobId);
      await loadStatus();
    } catch (err: any) { alert(err.response?.data?.detail || 'Failed to stop'); }
  };

  const handleQuickSend = async () => {
    if (!quickTo || !quickSubject || !quickBody) return;
    if (!activeSender) { alert('Please select an active sender first (Senders page).'); return; }
    setQuickSending(true);
    try {
      await sendSingleEmail(quickTo, quickSubject, quickBody);
      setQuickSent(true);
      setTimeout(() => setQuickSent(false), 3000);
      setQuickTo(''); setQuickSubject(''); setQuickBody('');
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to send');
    } finally { setQuickSending(false); }
  };

  const steps = ['Upload', 'Message', 'Send'];

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Send className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Send Emails</h1>
              <p className="text-slate-500 dark:text-slate-400 text-sm">Send bulk campaigns or quick individual emails</p>
            </div>
          </div>
          {/* Active Sender Badge */}
          <div className={`hidden sm:flex items-center gap-2 px-4 py-2 rounded-xl border text-sm font-medium ${
            activeSender
              ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200/50 dark:border-emerald-800/50 text-emerald-700 dark:text-emerald-400'
              : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200/50 dark:border-amber-800/50 text-amber-700 dark:text-amber-400'
          }`}>
            {activeSender ? (
              <><UserCheck size={16} /> {activeSender.email}</>
            ) : (
              <><AlertTriangle size={16} /> No sender active</>
            )}
          </div>
        </div>
      </motion.div>

      {/* Gmail Connect Card — individual users can connect their own Gmail
          to send via the Gmail API (same mechanism organizations use per-sender) */}
      {user?.role === 'individual' && user?.email && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="mb-6"
        >
          <ConnectGoogleButton
            targetEmail={user.email}
            title="Your Gmail Account"
            description="Connect Gmail to send your emails via the Gmail API (recommended over app password)."
            returnPath="/send-emails"
          />
        </motion.div>
      )}

      {/* Sender Warning Banner */}
      {!activeSender && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
          className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 rounded-2xl border border-amber-200/50 dark:border-amber-800/50 flex items-start gap-3"
        >
          <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-amber-800 dark:text-amber-300 text-sm">No active sender configured</p>
            <p className="text-sm text-amber-600 dark:text-amber-400/80 mt-0.5">
              You need to set an active sender before sending emails. Go to the <strong>Senders</strong> page to add and select a sender account.
            </p>
          </div>
        </motion.div>
      )}

      {/* Tab Switcher */}
      <div className="flex gap-2 mb-6">
        {(['bulk', 'quick'] as const).map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
              activeTab === tab
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-700 shadow-sm'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 border border-transparent'
            }`}
          >
            {tab === 'bulk' ? '📋 Bulk Campaign' : '⚡ Quick Send'}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {activeTab === 'quick' ? (
          <motion.div key="quick" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
            <div className="glass-card rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-5">
                <MailPlus size={20} className="text-indigo-500" />
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Quick Send — Single Email</h2>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Recipient Email</label>
                  <input type="email" value={quickTo} onChange={(e) => setQuickTo(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all"
                    placeholder="recipient@example.com" />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Subject</label>
                  <input type="text" value={quickSubject} onChange={(e) => setQuickSubject(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all"
                    placeholder="Email subject" />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Message</label>
                  <textarea value={quickBody} onChange={(e) => setQuickBody(e.target.value)} rows={6}
                    className="w-full px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all"
                    placeholder="Write your email message here..." />
                </div>

                <motion.button whileHover={{ scale: 1.01 }} whileTap={{ scale: 0.98 }}
                  onClick={handleQuickSend} disabled={quickSending || !quickTo || !quickSubject || !quickBody || !activeSender}
                  className="w-full py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-semibold rounded-xl hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-2"
                >
                  {quickSending ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Sending...</>
                  ) : quickSent ? (
                    <><CheckCircle size={18} /> Sent!</>
                  ) : (
                    <><Send size={16} /> Send Email</>
                  )}
                </motion.button>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div key="bulk" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
            {/* Step Indicator */}
            {!manualMode && (
              <div className="flex items-center gap-2 mb-8">
                {steps.map((step, i) => (
                  <div key={step} className="flex items-center gap-2">
                    <motion.button
                      whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      onClick={() => setActiveStep(i)}
                      className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
                        activeStep === i
                          ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-700'
                          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
                      }`}
                    >
                      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                        activeStep === i ? 'bg-indigo-600 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                      }`}>{i + 1}</span>
                      {step}
                    </motion.button>
                    {i < steps.length - 1 && <div className="w-8 h-px bg-slate-200 dark:bg-slate-700" />}
                  </div>
                ))}
              </div>
            )}

            <AnimatePresence mode="wait">
              {!manualMode && activeStep === 0 && (
                <motion.div key="step1" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} className="space-y-4">
                  <div className="glass-card rounded-2xl p-6">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
                      <FileUp size={20} className="text-indigo-500" />
                      Upload Contact Excel
                    </h2>
                    <div onClick={() => fileInputRef.current?.click()}
                      className="relative border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-10 text-center cursor-pointer hover:border-indigo-400 dark:hover:border-indigo-500 transition-all group bg-slate-50/50 dark:bg-slate-800/30"
                    >
                      <input ref={fileInputRef} type="file" accept=".xlsx,.xls" onChange={handleFileUpload} className="hidden" />
                      <div className="w-14 h-14 rounded-2xl bg-indigo-50 dark:bg-indigo-900/20 flex items-center justify-center mx-auto mb-4 group-hover:scale-110 transition-transform">
                        <FileText className="w-7 h-7 text-indigo-500" />
                      </div>
                      <p className="text-slate-600 dark:text-slate-400 font-medium">
                        {uploadedFile ? uploadedFile.name : 'Drop your Excel file here or click to browse'}
                      </p>
                      <p className="text-sm text-slate-400 mt-1">Supports .xlsx and .xls formats</p>
                    </div>
                    {uploadData && (
                      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-4 p-4 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl border border-emerald-200/50 dark:border-emerald-800/50">
                        <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 text-sm font-medium mb-2">
                          <CheckCircle size={16} /> File loaded successfully
                        </div>
                        <p className="text-sm text-emerald-600 dark:text-emerald-400/80">{uploadData.rows_count} contacts found</p>
                      </motion.div>
                    )}
                  </div>

                  {/* Attachments Section */}
                  <div className="glass-card rounded-2xl p-6">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
                      <Paperclip size={20} className="text-indigo-500" />
                      Attachments <span className="text-sm font-normal text-slate-400">(Optional)</span>
                    </h2>
                    <input ref={attachInputRef} type="file" multiple onChange={handleAttachFiles} className="hidden" />
                    <button onClick={() => attachInputRef.current?.click()}
                      className="px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors text-sm font-medium"
                    >Add Files</button>
                    {attachments.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {attachments.map((f, i) => (
                          <span key={i} className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-lg text-sm">
                            {f.name}
                            <button onClick={() => setAttachments(attachments.filter((_, j) => j !== i))}>
                              <X size={14} className="text-slate-400 hover:text-rose-500" />
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex justify-end">
                    <button onClick={() => setActiveStep(1)}
                      disabled={!uploadData}
                      className="px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl font-medium hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-500/25"
                    >Next Step</button>
                  </div>
                </motion.div>
              )}

              {!manualMode && activeStep === 1 && (
                <motion.div key="step2" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} className="space-y-4">
                  <div className="glass-card rounded-2xl p-6">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
                      <Sparkles size={20} className="text-indigo-500" />
                      Create Message
                    </h2>
                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Subject</label>
                        <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)}
                          className="w-full px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all"
                          placeholder="Email subject line" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">Objective</label>
                        <textarea value={objective} onChange={(e) => setObjective(e.target.value)} rows={2}
                          className="w-full px-4 py-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all"
                          placeholder="What is the main message?" />
                        <button onClick={handleGenerate} disabled={loading || !objective}
                          className="mt-2 px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl text-sm font-medium hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 transition-all"
                        ><Zap size={16} className="inline mr-1.5" /> Generate Template</button>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                          Message Template <span className="text-slate-400 font-normal">(use {'{first_name}'})</span>
                        </label>
                        <textarea value={messageTemplate} onChange={(e) => setMessageTemplate(e.target.value)} rows={8}
                          className="w-full px-4 py-3 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all font-mono text-sm"
                          placeholder="Hi {first_name},&#10;&#10;Your message here..." />
                        <div className="mt-3 flex gap-2">
                          <button onClick={handleEnhance} disabled={loading || !messageTemplate}
                            className="px-4 py-2 bg-gradient-to-r from-violet-600 to-purple-600 text-white rounded-xl text-sm font-medium hover:from-violet-700 hover:to-purple-700 disabled:opacity-50 transition-all"
                          ><Sparkles size={16} className="inline mr-1.5" /> AI Enhance</button>
                          <button onClick={handlePreview} disabled={loading || !messageTemplate || !uploadData}
                            className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl text-sm font-medium hover:bg-slate-300 dark:hover:bg-slate-600 disabled:opacity-50 transition-all"
                          ><Eye size={16} className="inline mr-1.5" /> Preview</button>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-between">
                    <button onClick={() => setActiveStep(0)}
                      className="px-6 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl font-medium hover:bg-slate-300 dark:hover:bg-slate-600 transition-all"
                    >Back</button>
                    <button onClick={() => setActiveStep(2)}
                      disabled={!messageTemplate}
                      className="px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl font-medium hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-500/25"
                    >Continue to Send</button>
                  </div>
                </motion.div>
              )}

              {!manualMode && activeStep === 2 && (
                <motion.div key="step3" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }} className="space-y-4">
                  <div className="glass-card rounded-2xl p-6">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4 flex items-center gap-2">
                      <Send size={20} className="text-indigo-500" />
                      Send Campaign
                    </h2>

                    {/* Send buttons */}
                    <div className="flex flex-wrap gap-3">
                      <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                        onClick={handleSend} disabled={sending || !uploadData || !subject || !messageTemplate || !activeSender}
                        className="px-6 py-3 bg-gradient-to-r from-emerald-600 to-teal-600 text-white font-semibold rounded-xl hover:from-emerald-700 hover:to-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-emerald-500/25"
                      >
                        {sending ? 'Sending...' : `Auto Send to ${uploadData?.rows_count || 0} Recipients`}
                      </motion.button>
                      <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                        onClick={() => { setManualMode(true); setActiveStep(-1); handleInitManual(); }}
                        disabled={loading || !uploadData || !subject || !messageTemplate || !activeSender}
                        className="px-6 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-semibold rounded-xl hover:from-indigo-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-500/25 flex items-center gap-2"
                      ><Play size={18} /> Manual Review</motion.button>
                    </div>

                    {/* Emergency Stop - visible during sending */}
                    {sending && (
                      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-4">
                        <div className="p-4 bg-rose-50 dark:bg-rose-900/20 rounded-xl border border-rose-200/50 dark:border-rose-800/50">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-rose-700 dark:text-rose-400">
                              <span className="relative flex h-3 w-3">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75" />
                                <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500" />
                              </span>
                              <span className="font-medium text-sm">Sending in progress...</span>
                            </div>
                            <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                              onClick={() => handleEmergencyStop(currentJobId ?? undefined)}
                              className="px-5 py-2 bg-gradient-to-r from-rose-600 to-pink-600 text-white font-semibold rounded-xl hover:from-rose-700 hover:to-pink-700 transition-all shadow-lg shadow-rose-500/25 flex items-center gap-2 text-sm"
                            >
                              <StopCircle size={16} />
                              EMERGENCY STOP
                            </motion.button>
                          </div>
                        </div>
                      </motion.div>
                    )}

                    {/* Emergency stop from status */}
                    {status?.send_in_progress && !sending && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4">
                        <div className="p-3 bg-rose-50 dark:bg-rose-900/20 rounded-xl border border-rose-200/50 dark:border-rose-800/50 flex items-center justify-between">
                          <span className="text-sm text-rose-700 dark:text-rose-400">A send job is running in the background</span>
                          <button onClick={() => handleEmergencyStop(status?.jobs?.find(j => j.in_progress)?.job_id)}
                            className="px-4 py-1.5 bg-rose-600 text-white text-sm rounded-lg hover:bg-rose-700 transition-colors flex items-center gap-1.5"
                          ><StopCircle size={14} /> Stop</button>
                        </div>
                      </motion.div>
                    )}
                  </div>
                  <div className="flex justify-between">
                    <button onClick={() => setActiveStep(1)}
                      className="px-6 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl font-medium hover:bg-slate-300 dark:hover:bg-slate-600 transition-all"
                    >Back</button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Manual Mode */}
            <AnimatePresence>
              {manualMode && (
                <motion.div key="manual" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <div className="glass-card rounded-2xl p-6">
                    <div className="flex items-center justify-between mb-5">
                      <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                        <Users size={20} className="text-indigo-500" />
                        Manual Send
                      </h2>
                      <div className="flex gap-2">
                        <motion.button whileTap={{ scale: 0.95 }}
                          onClick={async () => { await handleInitManual(); setManualCurrentIndex(0); }}
                          disabled={loading}
                          className="px-3 py-1.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 rounded-xl text-xs font-medium hover:bg-indigo-200 dark:hover:bg-indigo-900/50 transition-colors flex items-center gap-1"
                        ><RefreshCw size={12} /> Reload</motion.button>
                        <button onClick={() => { setManualMode(false); setActiveStep(2); }}
                          className="px-3 py-1.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl text-xs font-medium hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors flex items-center gap-1"
                        ><ArrowLeft size={12} /> Back</button>
                      </div>
                    </div>

                    {manualContacts.length === 0 ? (
                      <div className="text-center py-8 text-slate-500">
                        <p>No contacts loaded. Upload an Excel file first.</p>
                        <button onClick={() => { setManualMode(false); setActiveStep(0); }}
                          className="mt-3 px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm hover:bg-indigo-700 transition-colors"
                        >Go to Upload</button>
                      </div>
                    ) : (
                      <>
                        {/* Contact Card */}
                        {(() => {
                          const contact = manualContacts[manualCurrentIndex];
                          if (!contact) return null;
                          const statusColors: Record<string, string> = {
                            sent: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
                            skipped: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
                            failed: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800',
                            pending: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800',
                          };
                          return (
                            <motion.div key={manualCurrentIndex} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                              className="bg-gradient-to-br from-slate-50 to-indigo-50/30 dark:from-slate-800/50 dark:to-indigo-900/10 rounded-2xl p-6 border border-slate-200/50 dark:border-slate-700/50"
                            >
                              <div className="flex items-start gap-4 mb-4">
                                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xl font-bold shadow-lg">
                                  {contact.to?.charAt(0).toUpperCase() || '?'}
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm text-slate-500 dark:text-slate-400 mb-0.5">
                                    Contact {manualCurrentIndex + 1} of {manualContacts.length}
                                  </p>
                                  <p className="text-lg font-semibold text-slate-900 dark:text-white truncate">
                                    {contact.to}
                                  </p>
                                </div>
                                <span className={`px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap border ${statusColors[contact.status] || statusColors.pending}`}>
                                  {contact.status === 'sent' ? 'Sent' : contact.status === 'skipped' ? 'Skipped' : contact.status === 'failed' ? 'Failed' : 'Pending'}
                                </span>
                              </div>

                              <div className="space-y-3 mb-4">
                                <div>
                                  <p className="text-xs font-medium text-slate-400 mb-1.5">SUBJECT</p>
                                  <input type="text" value={manualSubject} onChange={(e) => setManualSubject(e.target.value)}
                                    className="w-full px-4 py-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all text-sm"
                                    placeholder="Email subject" />
                                </div>
                                <div>
                                  <p className="text-xs font-medium text-slate-400 mb-1.5">MESSAGE</p>
                                  <textarea value={manualMessage} onChange={(e) => setManualMessage(e.target.value)} rows={6}
                                    className="w-full px-4 py-2.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500 dark:text-white outline-none transition-all text-sm"
                                    placeholder="Email message" />
                                </div>
                              </div>

                              <div className="flex gap-2">
                                <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                                  onClick={() => handleSendByIndex(manualCurrentIndex)}
                                  disabled={loading || contact.status === 'sent' || !messageTemplate}
                                  className="flex-1 px-5 py-3 bg-gradient-to-r from-emerald-600 to-emerald-500 text-white rounded-xl font-medium hover:from-emerald-700 hover:to-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center gap-2"
                                ><Send size={16} /> Send</motion.button>
                                <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                                  onClick={() => handleSendByIndex(manualCurrentIndex, true)}
                                  disabled={loading || contact.status === 'skipped' || contact.status === 'sent'}
                                  className="flex-1 px-5 py-3 bg-gradient-to-r from-amber-600 to-amber-500 text-white rounded-xl font-medium hover:from-amber-700 hover:to-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2"
                                ><X size={16} /> Skip</motion.button>
                              </div>
                            </motion.div>
                          );
                        })()}

                        {/* Navigation */}
                        <div className="mt-4 flex items-center justify-between gap-2">
                          <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                            onClick={() => setManualCurrentIndex(Math.max(0, manualCurrentIndex - 1))}
                            disabled={manualCurrentIndex === 0}
                            className="px-5 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl font-medium hover:bg-slate-300 dark:hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5"
                          ><ArrowLeft size={16} /> Previous</motion.button>
                          <span className="text-xs text-slate-400">
                            {manualCurrentIndex + 1} / {manualContacts.length}
                          </span>
                          <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                            onClick={() => setManualCurrentIndex(Math.min(manualContacts.length - 1, manualCurrentIndex + 1))}
                            disabled={manualCurrentIndex >= manualContacts.length - 1}
                            className="px-5 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-xl font-medium hover:bg-slate-300 dark:hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5"
                          >Next <ArrowLeft size={16} className="rotate-180" /></motion.button>
                        </div>

                        {/* Progress Bar */}
                        <div className="mt-5">
                          <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                            <span>Progress</span>
                            <span>{manualContacts.filter((c: any) => c.status !== 'pending').length} / {manualContacts.length}</span>
                          </div>
                          <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                            <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500"
                              style={{ width: `${(manualContacts.filter((c: any) => c.status !== 'pending').length / Math.max(manualContacts.length, 1)) * 100}%` }}
                            />
                          </div>
                        </div>

                        {/* Summary bar */}
                        <div className="mt-4 flex items-center gap-4 p-3 bg-slate-50 dark:bg-slate-800/30 rounded-xl text-xs text-slate-500">
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-emerald-500" /> Sent: {manualContacts.filter((c: any) => c.status === 'sent').length}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-amber-500" /> Skipped: {manualContacts.filter((c: any) => c.status === 'skipped').length}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-rose-500" /> Failed: {manualContacts.filter((c: any) => c.status === 'failed').length}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-slate-300 dark:bg-slate-600" /> Pending: {manualContacts.filter((c: any) => c.status === 'pending').length}
                          </span>
                          <span className="ml-auto font-medium">{manualContacts.length} total</span>
                        </div>
                      </>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview Modal */}
      <AnimatePresence>
        {showPreview && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 z-50"
          >
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white dark:bg-slate-900 rounded-2xl p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto shadow-2xl border border-slate-200/50 dark:border-slate-700/50"
            >
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Message Previews</h3>
                <button onClick={() => setShowPreview(false)}
                  className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                ><X size={16} /></button>
              </div>
              <div className="space-y-3">
                {previews.map((p, i) => (
                  <div key={i} className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/50 dark:border-slate-700/50">
                    <p className="text-xs font-medium text-slate-500 mb-2">To: {Object.values(p.recipient).join(', ')}</p>
                    <div className="text-sm whitespace-pre-wrap dark:text-slate-200">{p.message}</div>
                  </div>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Progress */}
      {status && <SendProgress status={status} />}
    </div>
  );
};

export default SendEmailsPage;