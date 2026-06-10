export interface User {
  id: number;
  name: string;
  email: string;
  role: 'individual' | 'organization';
}

export interface Sender {
  id: number;
  name: string;
  organization_name: string;
  email: string;
  password?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_use_tls?: boolean;
  verified?: boolean;
}

export interface ExcelUploadResponse {
  success: boolean;
  rows_count: number;
  columns: string[];
  first_name_column: string | null;
  email_column: string | null;
}

export interface EmailRow {
  [key: string]: string;
}

export interface PreviewItem {
  recipient: EmailRow;
  message: string;
}

export interface SendProgress {
  total: number;
  processed: number;
  delivered: number;
  failed: number;
  skipped: number;
  bounced: number;
  current_email: string | null;
  current_emails_summary: string;
  active_job_count: number;
}

export interface SendJob {
  job_id: string;
  from_email: string;
  subject: string;
  in_progress: boolean;
  started_at: string | null;
  completed_at: string | null;
  total: number;
  processed: number;
  delivered: number;
  failed: number;
  skipped: number;
  bounced: number;
  current_email: string;
}

export interface SendStatusResponse {
  success: boolean;
  send_in_progress: boolean;
  stop_requested: boolean;
  progress: SendProgress;
  jobs: SendJob[];
  active_job_count: number;
  last_batch: {
    at: string;
    from_email: string;
    subject: string;
    mode: string;
    total: number;
    delivered: number;
    failed: number;
    skipped: number;
    bounced: number;
    bounced_emails: string[];
    results: { email: string; status: string; detail: string }[];
  } | null;
  smtp_configured: boolean;
  delivery_note: string;
}

export interface EmailSnippet {
  uid: string;
  date: string;
  from: string;
  sender_email: string;
  subject: string;
  body: string;
  seen: boolean;
  flags: string[];
}

export interface InsightResponse {
  success: boolean;
  answer: string;
  intent: string;
  emails_used: number;
  senders_used: number;
  start_date: string | null;
  end_date: string | null;
  emails?: EmailSnippet[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}