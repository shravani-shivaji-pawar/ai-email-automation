import { useEffect, useState, useCallback } from 'react';
import { getGmailLoginUrl, getGmailStatus, disconnectGmail, type GmailStatus } from '../api';
import { useAuth } from '../AuthContext';

interface Props {
  /** Where to redirect after OAuth (defaults to /settings) */
  returnPath?: string;
}

export default function ConnectGoogleButton({ returnPath = '/settings' }: Props) {
  const { user } = useAuth();
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    if (!user?.email) return;
    try {
      const s = await getGmailStatus(user.email);
      setStatus(s);
    } catch {
      setError('Could not check Gmail connection status.');
    }
  }, [user?.email]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Handle redirect back from Google: /settings?gmail_connected=1  or  /dashboard?gmail_connected=1
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const flag = params.get('gmail_connected');
    if (flag === '1') {
      refreshStatus();
      params.delete('gmail_connected');
      window.history.replaceState(
        {},
        '',
        `${window.location.pathname}${params.toString() ? `?${params}` : ''}`,
      );
    } else if (flag === '0') {
      setError(params.get('error') || 'Gmail connection failed. Please try again.');
      params.delete('gmail_connected');
      params.delete('error');
      window.history.replaceState(
        {},
        '',
        `${window.location.pathname}${params.toString() ? `?${params}` : ''}`,
      );
    }
  }, [refreshStatus]);

  const handleConnect = async () => {
    if (!user?.email) return;
    setLoading(true);
    setError(null);
    try {
      const url = await getGmailLoginUrl(user.email);
      window.location.href = url;
    } catch {
      setError('Could not start Google connection.');
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!user?.email) return;
    setLoading(true);
    setError(null);
    try {
      await disconnectGmail(user.email);
      setStatus({ connected: false });
    } catch {
      setError('Could not disconnect Gmail account.');
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  return (
    <div className="glass-card rounded-xl p-5 flex flex-col gap-3 max-w-md animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-white">Google / Gmail Account</h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Connect Gmail to send emails via the Gmail API.
          </p>
        </div>
        {status === null ? (
          <span className="text-xs px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400">
            Checking…
          </span>
        ) : status.connected ? (
          <span className="text-xs px-2 py-1 rounded-full bg-green-100 text-green-700 font-medium">
            ✓ Connected
          </span>
        ) : (
          <span className="text-xs px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 font-medium">
            Not connected
          </span>
        )}
      </div>

      {status?.connected && status.connected_at && (
        <p className="text-xs text-slate-400">
          Connected since {new Date(status.connected_at).toLocaleString()}
        </p>
      )}

      {error && (
        <p className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      {status?.connected ? (
        <button
          onClick={handleDisconnect}
          disabled={loading}
          className="px-4 py-2 rounded-lg bg-red-50 text-red-700 text-sm font-medium hover:bg-red-100 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Disconnecting…' : 'Disconnect Gmail Account'}
        </button>
      ) : (
        <button
          onClick={handleConnect}
          disabled={loading || status === null}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50 transition-colors shadow-sm"
        >
          <GoogleIcon />
          {loading ? 'Redirecting…' : 'Connect Google Account'}
        </button>
      )}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6.1 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6.1 29.6 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.5 0 10.4-2 14-5.4l-6.5-5.5C29.6 35 26.9 36 24 36c-5.3 0-9.7-3.3-11.3-8l-6.6 5.1C9.6 39.6 16.3 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-0.8 2.3-2.3 4.2-4.2 5.6l6.5 5.5C41.4 35.9 44 30.5 44 24c0-1.3-.1-2.7-.4-3.5z" />
    </svg>
  );
}