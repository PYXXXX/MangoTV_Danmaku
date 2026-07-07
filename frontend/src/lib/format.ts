import type { RankingRow, RoundSession, VoteResult } from "../api/types";

export function formatCount(value: unknown): string {
  const number = Number(value || 0);
  if (number < 1000) return number.toLocaleString("zh-CN");
  const units = [
    { value: 1_000_000_000, suffix: "b" },
    { value: 1_000_000, suffix: "m" },
    { value: 1_000, suffix: "k" }
  ];
  const unit = units.find((item) => number >= item.value) ?? units[2];
  const scaled = number / unit.value;
  const digits = scaled < 10 ? 1 : 0;
  return scaled.toFixed(digits).replace(/\.0$/, "") + unit.suffix;
}

export function formatBytes(value: unknown): string {
  const number = Number(value || 0);
  if (!number) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let scaled = number;
  let index = 0;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  return `${scaled.toFixed(scaled >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(seconds: unknown): string {
  const total = Math.max(0, Number(seconds || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days} 天 ${String(hours).padStart(2, "0")} 小时`;
  if (hours) return `${hours} 小时 ${String(minutes).padStart(2, "0")} 分`;
  return `${minutes} 分钟`;
}

export function roundName(round?: RoundSession | null): string {
  return round?.displayName || round?.baseName || round?.name || "等待场次";
}

export function selectedResult(round?: RoundSession | null, requested = "rough"): { type: "rough" | "precise"; data: VoteResult } {
  if (!round) return { type: "rough", data: { voteCounts: {}, messageCount: 0, reviewCount: 0 } };
  const preciseAvailable = Boolean(round.results?.precise);
  const type = requested === "precise" && preciseAvailable ? "precise" : "rough";
  const fallback = { voteCounts: round.voteCounts || {}, messageCount: round.messageCount || 0, reviewCount: round.reviewCount || 0 };
  return { type, data: (round.results?.[type] || fallback) as VoteResult };
}

export function rankingRows(round?: RoundSession | null, result?: VoteResult): RankingRow[] {
  if (!round) return [];
  const counts = result?.voteCounts || round.voteCounts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  return (round.candidates || [])
    .map((candidate) => {
      const votes = Number(counts[candidate.id] || 0);
      return {
        candidateId: candidate.id,
        name: candidate.name,
        avatarUrl: candidate.avatarUrl,
        votes,
        percent: total ? Number(((votes / total) * 100).toFixed(1)) : 0,
        trend: 0
      };
    })
    .sort((a, b) => b.votes - a.votes || a.name.localeCompare(b.name, "zh-CN"))
    .map((item, index) => ({ ...item, leader: index === 0 }));
}

export function currentRound(sessions: RoundSession[] = [], activeSessionId?: string | null): RoundSession | null {
  const publishable = sessions.filter((item) => item.visibility !== "private" && item.kind !== "recording");
  return publishable.find((item) => item.id === activeSessionId)
    || publishable.find((item) => item.status === "running")
    || publishable[0]
    || sessions.find((item) => item.id === activeSessionId)
    || sessions[0]
    || null;
}
