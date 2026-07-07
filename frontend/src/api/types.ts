export type ServiceStatus = "running" | "idle" | "connected" | "enabled" | "disabled" | "recording" | "error" | string;

export interface Candidate {
  id: string;
  name: string;
  aliases?: string[];
  avatarUrl?: string;
}

export interface VoteResult {
  messageCount?: number;
  reviewCount?: number;
  voteCounts?: Record<string, number>;
  audit?: {
    inputMessages?: number;
    unresolvedReviewMessages?: number;
  };
}

export interface RecordingMarker {
  id: string;
  label: string;
  atSeconds: number;
  createdAt?: string;
}

export interface RecordingClip {
  id: string;
  label: string;
  startSeconds: number;
  endSeconds: number;
  url?: string;
  danmakuUrl?: string;
  rawDanmakuUrl?: string;
  analysisUrl?: string;
}

export interface Recording {
  roundId: string;
  status: string;
  hasVideo?: boolean;
  videoUrl?: string;
  durationSeconds?: number;
  fileSizeBytes?: number;
  sourceUrl?: string;
  error?: string;
  markers?: RecordingMarker[];
  clips?: RecordingClip[];
}

export interface RoundSession {
  id: string;
  activity?: string;
  activityId?: string;
  name: string;
  baseName?: string;
  displayName?: string;
  status: "running" | "stopped" | string;
  startedAt?: string;
  endedAt?: string;
  timeRange?: string;
  compactTimeRange?: string;
  pageUrl?: string;
  pageTitle?: string;
  messageCount?: number;
  reviewCount?: number;
  candidates?: Candidate[];
  voteCounts?: Record<string, number>;
  results?: {
    rough?: VoteResult | null;
    precise?: VoteResult | null;
  };
  resultImageUrl?: string;
  resultImageUrls?: {
    rough?: string;
    precise?: string;
  };
  defaultResultType?: "rough" | "precise";
  recording?: Recording | null;
}

export interface PublicState {
  schemaVersion?: number;
  activeSessionId?: string | null;
  publishedAt?: string;
  updatedAt?: string;
  defaults?: {
    activity?: string;
    mgtvUrl?: string;
    publicBaseUrl?: string;
    publicResultsUrl?: string;
  };
  sessions?: RoundSession[];
}

export interface MonitorView {
  config?: {
    enabled?: boolean;
    activity?: string;
    url?: string;
    autoDetectSource?: boolean;
    autoRecordVideo?: boolean;
    autoRecordDanmaku?: boolean;
    feishuNotify?: boolean;
    pollSeconds?: number;
    preferredQuality?: string;
  };
  state?: {
    status?: string;
    message?: string;
    lastCheckAt?: string;
    lastError?: string;
    quality?: string;
    taskRunning?: boolean;
  };
}

export interface SystemStatus {
  ok?: boolean;
  generatedAt?: string;
  systemTime?: string;
  startedAt?: string;
  uptimeSeconds?: number;
  process?: {
    pid?: number;
    name?: string;
    rssBytes?: number;
  };
  cpu?: {
    count?: number;
    loadPercent?: number | null;
    loadAverage?: number[];
  };
  memory?: {
    totalBytes?: number;
    availableBytes?: number;
    usedBytes?: number;
    processRssBytes?: number;
  };
  network?: {
    available?: boolean;
    rxBytes?: number;
    txBytes?: number;
  };
  disk?: {
    data?: { ok?: boolean; path?: string; totalBytes?: number; usedBytes?: number; freeBytes?: number; error?: string };
    recordings?: { ok?: boolean; path?: string; totalBytes?: number; usedBytes?: number; freeBytes?: number; error?: string };
  };
  services?: Record<string, { status?: ServiceStatus; message?: string; enabled?: boolean; activeCount?: number; progress?: unknown }>;
  monitor?: MonitorView;
  health?: {
    status?: "ok" | "warning" | "error" | string;
    restartRequired?: boolean;
    restartFields?: string[];
    recentErrorCount?: number;
  };
}

export interface SystemLogEvent {
  id?: string;
  time?: string;
  level?: "INFO" | "WARN" | "ERROR" | string;
  source?: string;
  summary?: string;
  detail?: string;
  roundId?: string;
}

export interface SystemLogsResponse {
  events?: SystemLogEvent[];
  items?: SystemLogEvent[];
  sources?: string[];
  nextCursor?: string;
}

export interface StudioBootstrap {
  generatedAt: string;
  publicState: PublicState;
  systemStatus?: SystemStatus;
  logs?: SystemLogEvent[];
}

export interface RankingRow {
  candidateId: string;
  name: string;
  avatarUrl?: string;
  votes: number;
  percent: number;
  trend?: number;
  leader?: boolean;
}
