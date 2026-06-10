import type { SendStatusResponse } from '../types';
import { motion } from 'framer-motion';

interface SendProgressProps {
  status: SendStatusResponse;
}

const SendProgress: React.FC<SendProgressProps> = ({ status }) => {
  const { progress, send_in_progress, stop_requested, jobs } = status;

  if (!send_in_progress && jobs.length === 0) return null;

  const percent = progress.total > 0 ? (progress.processed / progress.total) * 100 : 0;

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="glass-card rounded-2xl p-6 mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${send_in_progress ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'}`} />
          <h3 className="font-semibold text-slate-900 dark:text-white">Send Progress</h3>
        </div>
        {stop_requested && (
          <span className="px-3 py-1 text-xs font-medium bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400 rounded-full">
            Stopping...
          </span>
        )}
        {send_in_progress && (
          <span className="px-3 py-1 text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full">
            In Progress
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-5 gap-4 mb-4">
        {[
          { label: 'Total', value: progress.total, color: 'text-indigo-600 dark:text-indigo-400' },
          { label: 'Sent', value: progress.delivered, color: 'text-emerald-600 dark:text-emerald-400' },
          { label: 'Failed', value: progress.failed, color: 'text-rose-600 dark:text-rose-400' },
          { label: 'Bounced', value: progress.bounced, color: 'text-amber-600 dark:text-amber-400' },
          { label: 'Skipped', value: progress.skipped, color: 'text-slate-600 dark:text-slate-400' },
        ].map((s) => (
          <div key={s.label} className="text-center">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            <div className="text-xs text-slate-500">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="relative h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 rounded-full"
        />
      </div>
      <p className="text-xs text-slate-500 mt-1.5">{Math.round(percent)}% complete ({progress.processed}/{progress.total})</p>

      {progress.current_email && (
        <p className="mt-3 text-xs text-slate-500">Currently sending to: <span className="font-mono">{progress.current_email}</span></p>
      )}

      {jobs.filter(j => j.in_progress).map(job => (
        <motion.div key={job.job_id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className="mt-4 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/50 dark:border-slate-700/50"
        >
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="font-medium text-sm text-slate-900 dark:text-white">{job.from_email}</p>
              <p className="text-xs text-slate-500">{job.subject}</p>
            </div>
            <span className="px-2 py-1 text-[10px] font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 rounded-full">Active</span>
          </div>
          <div className="flex gap-4 text-xs text-slate-500">
            <span>{job.processed}/{job.total} processed</span>
            <span className="text-emerald-600">{job.delivered} sent</span>
            {job.failed > 0 && <span className="text-rose-600">{job.failed} failed</span>}
          </div>
        </motion.div>
      ))}

      {status.last_batch && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/50 dark:border-slate-700/50">
          <h4 className="font-medium text-sm text-slate-900 dark:text-white mb-2">Last Batch</h4>
          <div className="text-xs space-y-1 text-slate-500">
            <p>From: {status.last_batch.from_email}</p>
            <p>Subject: {status.last_batch.subject}</p>
            <p className="text-slate-700 dark:text-slate-300">{status.last_batch.delivered} delivered, {status.last_batch.failed} failed, {status.last_batch.bounced} bounced</p>
          </div>
        </motion.div>
      )}
    </motion.div>
  );
};

export default SendProgress;
