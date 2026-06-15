import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Upload, Send, Bot, TrendingUp, Mail, Users, Sparkles, ArrowRight, Activity } from 'lucide-react';
import { useAuth } from '../AuthContext';
import { getSendStatus, getSenders } from '../api';
import SendProgress from '../components/SendProgress';
import ConnectGoogleButton from '../components/ConnectGoogleButton';
import type { SendStatusResponse } from '../types';
import { motion } from 'framer-motion';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
};

const statVariants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: (i: number) => ({
    opacity: 1,
    scale: 1,
    transition: { delay: i * 0.1, duration: 0.4 },
  }),
};

const DashboardPage: React.FC = () => {
  const { user } = useAuth();
  const [status, setStatus] = useState<SendStatusResponse | null>(null);
  const [senderCount, setSenderCount] = useState(0);

  useEffect(() => {
    loadStatus();
    if (user?.role === 'organization') {
      getSenders(user.id).then((res) => setSenderCount(res.data.senders?.length || 0));
    }
  }, [user]);

  const loadStatus = async () => {
    try {
      const res = await getSendStatus();
      setStatus(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const stats = [
    { label: 'Delivered', value: status?.progress.delivered || 0, icon: Send, color: 'from-emerald-500 to-teal-500', bg: 'emerald' },
    { label: 'Failed', value: status?.progress.failed || 0, icon: Mail, color: 'from-rose-500 to-pink-500', bg: 'rose' },
    { label: 'Bounced', value: status?.progress.bounced || 0, icon: TrendingUp, color: 'from-amber-500 to-orange-500', bg: 'amber' },
    { label: 'Processed', value: status?.progress.processed || 0, icon: Activity, color: 'from-indigo-500 to-purple-500', bg: 'indigo' },
  ];

  const quickActions = [
    {
      to: '/send-emails',
      label: 'Send Emails',
      desc: 'Upload Excel and send bulk emails',
      icon: Upload,
      gradient: 'from-indigo-500 via-purple-500 to-pink-500',
      shadow: 'shadow-indigo-500/25',
    },
    ...(user?.role === 'organization'
      ? [
          {
            to: '/ai-agent',
            label: 'AI Agent',
            desc: 'Query emails with AI',
            icon: Bot,
            gradient: 'from-violet-500 via-purple-500 to-fuchsia-500',
            shadow: 'shadow-violet-500/25',
          },
          {
            to: '/senders',
            label: 'Senders',
            desc: `${senderCount} sender accounts`,
            icon: Users,
            gradient: 'from-emerald-500 to-teal-500',
            shadow: 'shadow-emerald-500/25',
          },
        ]
      : [
          // ✅ Individual users get a shortcut to Settings/Gmail
          {
            to: '/settings',
            label: 'Gmail Settings',
            desc: 'Connect your Gmail account',
            icon: Mail,
            gradient: 'from-emerald-500 to-teal-500',
            shadow: 'shadow-emerald-500/25',
          },
        ]),
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      {/* Welcome Header */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-10">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center shadow-lg shadow-indigo-500/25">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
              Welcome back, {user?.name?.split(' ')[0]}!
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              Here's your email campaign overview
            </p>
          </div>
        </div>
      </motion.div>

      {/* Quick Actions */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-10"
      >
        {quickActions.map((action) => (
          <motion.div key={action.to} variants={itemVariants}>
            <Link
              to={action.to}
              className="group relative block overflow-hidden rounded-2xl bg-white dark:bg-slate-800/50 border border-slate-200/50 dark:border-slate-700/50 hover:shadow-xl transition-all duration-300"
            >
              <div className="absolute inset-0 bg-gradient-to-br from-transparent via-transparent to-indigo-50/50 dark:to-indigo-900/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <div className="relative p-6">
                <div className="flex items-start justify-between mb-4">
                  <div
                    className={`w-12 h-12 rounded-xl bg-gradient-to-br ${action.gradient} ${action.shadow} flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}
                  >
                    <action.icon className="w-6 h-6 text-white" />
                  </div>
                  <ArrowRight className="w-5 h-5 text-slate-300 dark:text-slate-600 group-hover:text-indigo-500 group-hover:translate-x-1 transition-all duration-300" />
                </div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">{action.label}</h3>
                <p className="text-sm text-slate-500 dark:text-slate-400">{action.desc}</p>
              </div>
            </Link>
          </motion.div>
        ))}
      </motion.div>

      {/* ✅ Gmail Connect Card — shown only to individual users, inline on dashboard */}
      {user?.role === 'individual' && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="mb-10"
        >
          <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
            Gmail Connection
          </h2>
          <ConnectGoogleButton returnPath="/dashboard" />
        </motion.div>
      )}

      {/* Stats Grid */}
      <motion.div initial="hidden" animate="visible" className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
        {stats.map((stat, i) => (
          <motion.div
            key={stat.label}
            custom={i}
            variants={statVariants}
            className="relative overflow-hidden rounded-2xl bg-white dark:bg-slate-800/50 border border-slate-200/50 dark:border-slate-700/50 p-5"
          >
            <div
              className={`absolute top-0 right-0 w-24 h-24 bg-gradient-to-br ${stat.color} opacity-5 rounded-bl-[3rem]`}
            />
            <div className="relative">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium text-slate-500 dark:text-slate-400">{stat.label}</span>
                <div
                  className={`w-9 h-9 rounded-lg bg-gradient-to-br ${stat.color} bg-opacity-10 flex items-center justify-center`}
                >
                  <stat.icon className={`w-4 h-4 text-${stat.bg}-600 dark:text-${stat.bg}-400`} />
                </div>
              </div>
              <p className="text-3xl font-bold text-slate-900 dark:text-white">{stat.value}</p>
            </div>
          </motion.div>
        ))}
      </motion.div>

      {/* Send Progress */}
      {status && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.4 }}
        >
          <SendProgress status={status} />
        </motion.div>
      )}
    </div>
  );
};

export default DashboardPage;