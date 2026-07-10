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
  kind?: "manual" | "auto" | string;
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
  startedAt?: string;
  timelineOriginAt?: string;
  videoStartedAt?: string;
  danmakuStartedAt?: string;
  endedAt?: string;
  stopRequestedAt?: string;
  alignment?: {
    version?: number;
    clock?: string;
    method?: string;
    timelineOriginAt?: string;
    videoStartedAt?: string;
    danmakuStartedAt?: string;
    videoStartOffsetSeconds?: number;
    danmakuStartOffsetSeconds?: number;
    danmakuPollingSeconds?: number;
  };
  autoSplitSeconds?: number;
  autoSplitStatus?: string;
  autoSplitMessage?: string;
  canPostProcess?: boolean;
  postProcessReason?: string;
  markers?: RecordingMarker[];
  clips?: RecordingClip[];
}

export interface RecordingTimeline {
  roundId: string;
  durationSeconds?: number;
  bucketSeconds?: number;
  danmakuDensity?: Array<{ t: number; count: number }>;
  markers?: RecordingMarker[];
  clips?: RecordingClip[];
  recording?: Recording;
}

export interface RoundSession {
  id: string;
  activity?: string;
  activityId?: string;
  name: string;
  baseName?: string;
  displayName?: string;
  kind?: "realtime" | "recording" | "analysis" | string;
  visibility?: "public" | "private" | string;
  sourceRoundId?: string;
  status: "running" | "stopped" | string;
  startedAt?: string;
  endedAt?: string;
  stoppedAt?: string;
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

export interface ActivityItem {
  id: string;
  name: string;
  url?: string;
  status?: string;
  monitorEnabled?: boolean;
  roundCount?: number;
  runningRoundCount?: number;
  messageCount?: number;
  createdAt?: string;
  updatedAt?: string;
  monitor?: MonitorView;
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
    activityId?: string;
    cameraId?: string;
    roomId?: string;
    sourceInputMode?: "direct_camera" | "activity_page" | string;
  };
  state?: {
    status?: string;
    message?: string;
    lastCheckAt?: string;
    lastError?: string;
    quality?: string;
    availableQualities?: string[];
    taskRunning?: boolean;
    activityId?: string;
    cameraId?: string;
    roomId?: string;
    sourceInputMode?: "direct_camera" | "activity_page" | string;
    liveStatus?: "upcoming" | "live" | "ended" | "unknown" | string;
    streamBeginTime?: string;
    streamBeginTimestamp?: number;
    streamEndTime?: string;
    streamEndTimestamp?: number;
  };
}

export interface SourceDetectionResult {
  ok?: boolean;
  error?: string;
  message?: string;
  quality?: string;
  actualQuality?: string;
  availableQualities?: string[];
  streamUrl?: string;
  streamUrlConfigured?: boolean;
  loginRequired?: boolean;
  vipRequired?: boolean | "unknown";
  candidates?: number;
  pageUrl?: string;
  activityId?: string;
  cameraId?: string;
  resolvedFrom?: string;
  liveStatus?: "upcoming" | "live" | "ended" | "unknown" | string;
  serverTimestamp?: number;
  streamBeginTimestamp?: number;
  streamEndTimestamp?: number;
  streamBeginTime?: string;
  streamEndTime?: string;
  preview?: boolean;
  cameraName?: string;
  roomId?: string;
  sourceInputMode?: "direct_camera" | "activity_page" | string;
}

export interface MgtvAuthStatus {
  status?: "idle" | "pending" | "success" | "error" | string;
  message?: string;
  error?: string;
  screenshot?: string;
  expiresAt?: number;
  cookieConfigured?: boolean;
  loginProtocol?: string;
  loginProtocolAvailable?: boolean;
  user?: {
    uid?: string;
    nickname?: string;
    isVip?: boolean;
    vipType?: string;
  };
}

export interface FeishuBindingStatus {
  status?: "idle" | "pending" | "bound" | "success" | "error" | string;
  message?: string;
  error?: string;
  userCode?: string;
  verificationUrl?: string;
  expiresAt?: number;
  boundAt?: string;
  openId?: string;
  tenantBrand?: string;
  warning?: string;
  enabled?: boolean;
  connectionMode?: string;
  appId?: string;
  appSecretConfigured?: boolean;
  allowedOpenIds?: string[];
  allowedChatIds?: string[];
  workerAlive?: boolean;
}

export interface FeishuPushResult {
  ok?: boolean;
  count?: number;
  failedCount?: number;
  prunedOpenIdCount?: number;
  prunedOpenIds?: string[];
  sent?: Array<{
    receiveId?: string;
    receiveIdType?: string;
  }>;
  failed?: Array<{
    receiveId?: string;
    receiveIdType?: string;
    code?: string;
    error?: string;
  }>;
}

export interface UpdateProgress {
  status?: "idle" | "running" | "complete" | "failed" | string;
  stage?: string;
  percent?: number;
  detail?: string;
  speed?: string;
  updatedAt?: string;
  logs?: string[];
  restartScheduled?: boolean;
}

export interface UpdateStatus {
  ok?: boolean;
  repoRoot?: string;
  currentSha?: string;
  currentShort?: string;
  branch?: string;
  remote?: string;
  remoteBranch?: string;
  remoteUrl?: string;
  remoteSha?: string;
  remoteShort?: string;
  dirty?: boolean;
  updateAvailable?: boolean;
  inProgress?: boolean;
  canApply?: boolean;
  blockers?: string[];
  restartWillApplyConfig?: boolean;
  lastUpdate?: unknown;
  progress?: UpdateProgress;
}

export interface SystemStatus {
  ok?: boolean;
  generatedAt?: string;
  systemTime?: string;
  timezone?: string;
  platform?: string;
  python?: string;
  host?: SystemHostInfo;
  backup?: SystemBackupInfo;
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
    model?: string;
    architecture?: string;
    temperature?: SystemCpuTemperature;
    temperatureCelsius?: number | null;
    temperatureAvailable?: boolean;
    temperatureSource?: string;
    temperatureLabel?: string;
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
  services?: Record<string, {
    status?: ServiceStatus;
    message?: string;
    enabled?: boolean;
    activeCount?: number;
    activeRoundId?: string | null;
    activeRoundIds?: string[];
    taskRunning?: boolean;
    configured?: boolean;
    quality?: string;
    availableQualities?: string[];
    detectedAt?: string;
    progress?: unknown;
  }>;
  monitor?: MonitorView;
  health?: {
    status?: "ok" | "warning" | "error" | string;
    restartRequired?: boolean;
    restartFields?: string[];
    recentErrorCount?: number;
  };
}

export interface SystemCpuTemperature {
  available?: boolean;
  celsius?: number | null;
  label?: string;
  source?: string;
  error?: string;
  sensors?: Array<{ label?: string; celsius?: number; source?: string }>;
}

export interface SystemBackupInfo {
  available?: boolean;
  latestAt?: string;
  path?: string;
  name?: string;
  sizeBytes?: number;
  count?: number;
  items?: Array<{ path?: string; name?: string; sizeBytes?: number; updatedAt?: string }>;
}

export interface SystemHostInfo {
  ok?: boolean;
  generatedAt?: string;
  hostname?: string;
  platform?: string;
  system?: string;
  release?: string;
  version?: string;
  machine?: string;
  python?: string;
  process?: {
    pid?: number;
    name?: string;
    rssBytes?: number;
  };
  paths?: {
    repoRoot?: string;
    config?: string;
    storage?: string;
    recordings?: string;
  };
  cpu?: {
    model?: string;
    architecture?: string;
    temperature?: SystemCpuTemperature;
  };
  backup?: SystemBackupInfo;
}

export interface SystemLogEvent {
  id?: string;
  time?: string;
  level?: "INFO" | "WARN" | "ERROR" | string;
  source?: string;
  sourceLabel?: string;
  summary?: string;
  detail?: string;
  roundId?: string;
  host?: string;
  command?: string;
  errorMessage?: string;
  remediation?: string[];
  [key: string]: unknown;
}

export interface SystemLogTimelineItem {
  id?: string;
  time?: string;
  level?: "INFO" | "WARN" | "ERROR" | string;
  source?: string;
  sourceLabel?: string;
  summary?: string;
  roundId?: string;
}

export interface SystemLogsResponse {
  ok?: boolean;
  generatedAt?: string;
  events?: SystemLogEvent[];
  items?: SystemLogEvent[];
  sources?: string[];
  availableSources?: string[];
  sourceLabels?: Record<string, string>;
  levels?: string[];
  availableLevels?: string[];
  levelCounts?: Record<string, number>;
  sourceCounts?: Record<string, number>;
  timeline?: SystemLogTimelineItem[];
  cursor?: number;
  limit?: number;
  previousCursor?: string;
  nextCursor?: string;
  total?: number;
}

export interface SystemMetricsPoint {
  time?: string;
  cpuPercent?: number;
  memoryPercent?: number;
  rxBytesPerSecond?: number;
  txBytesPerSecond?: number;
  danmakuPerSecond?: number;
  collectorActive?: number;
}

export interface SystemMetricsResponse {
  ok?: boolean;
  generatedAt?: string;
  window?: string;
  points?: SystemMetricsPoint[];
}

export interface SystemLogSummary {
  ok?: boolean;
  generatedAt?: string;
  total?: number;
  levelCounts?: Record<string, number>;
  sourceCounts?: Record<string, number>;
  latestError?: SystemLogEvent | null;
  summary?: string;
  suggestions?: string[];
}

export interface StudioBootstrap {
  generatedAt: string;
  defaults?: {
    activityName?: string;
    publicResultsUrl?: string;
  };
  activity?: ActivityItem | null;
  activities?: ActivityItem[];
  monitor?: MonitorView;
  activeRound?: RoundSession | null;
  rounds?: RoundSession[];
  recordings?: Recording[];
  publicState: PublicState;
  systemStatus?: SystemStatus;
  logs?: SystemLogEvent[];
  settings?: unknown;
  permissions?: {
    operatorAuthenticated?: boolean;
  };
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
