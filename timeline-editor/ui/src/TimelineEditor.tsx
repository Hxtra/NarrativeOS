/**
 * NarrativeOS Timeline Editor
 *
 * A read-only state adapter for NarrativeOS production artifacts, with a
 * narrow write path (shot trim) that goes through the API server's
 * validated revision endpoint.
 *
 * This component does not fabricate data. Every artifact-derived value it
 * displays is checked against `present: boolean` before rendering, because
 * a missing artifact (e.g. assets.json in a simulation project) is a
 * different fact than an empty one, and conflating them hides real
 * production state from the person using this UI.
 *
 * API shape verified against timeline-editor/server/timeline_api_server.py
 * and its test suite (timeline-editor/tests/test_timeline_api_server.py),
 * which runs the real scripts/simulate_documentary.py script.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Types — mirrors the actual API response, not an idealized schema
// ---------------------------------------------------------------------------

interface ArtifactEnvelope<T> {
  present: boolean;
  data: T | null;
  error?: string;
}

interface Shot {
  shot_id: string;
  asset_id: string;
  start: number;
  end: number;
  source_start?: number;
  motion: "static" | "slow_zoom_in" | "slow_zoom_out";
  transition: string;
  status: "approved" | "simulation_approved" | string;
}

interface TimelineData {
  schema_version: number;
  status: string;
  output?: { width: number; height: number; fps: number };
  tracks: Record<string, string>;
  shots: Shot[];
}

interface EvidenceStatus {
  level: "green" | "yellow" | "red";
  reasons: string[];
  asset_id?: string;
  rights_status?: string | null;
  evidence_frame_count?: number;
  usable_interval?: [number, number];
  is_simulation?: boolean;
}

interface ProjectResponse {
  project_id: string;
  artifacts: Record<string, ArtifactEnvelope<any>>;
  evidence_by_shot: Record<string, EvidenceStatus>;
  events: { present: boolean; items: any[] };
  loaded_at: string;
}

interface ShotEvidenceResponse {
  shot_id: string;
  shot: Shot;
  shot_spec: ArtifactEnvelope<any>;
  evidence: EvidenceStatus;
  claim_links: any[];
  claims: any[];
  overlapping_audio_events: any[];
  editorial_note: any | null;
}

// ---------------------------------------------------------------------------
// API client — small, explicit, no silent fallback to fake data on error
// ---------------------------------------------------------------------------

class TimelineApiError extends Error {
  status: number;
  detail?: unknown;
  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

class TimelineApiClient {
  private baseUrl: string;
  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = await res.json();
      } catch {
        detail = await res.text();
      }
      throw new TimelineApiError(`Request to ${path} failed (${res.status})`, res.status, detail);
    }
    return res.json() as Promise<T>;
  }

  getProject(projectId: string): Promise<ProjectResponse> {
    return this.request(`/api/project/${encodeURIComponent(projectId)}`);
  }

  getShotEvidence(projectId: string, shotId: string): Promise<ShotEvidenceResponse> {
    return this.request(
      `/api/project/${encodeURIComponent(projectId)}/evidence/${encodeURIComponent(shotId)}`
    );
  }

  submitRevision(
    projectId: string,
    revision: { shot_id: string; new_start?: number; new_end?: number; reason: string }
  ): Promise<unknown> {
    return this.request(`/api/project/${encodeURIComponent(projectId)}/revision`, {
      method: "POST",
      body: JSON.stringify(revision),
    });
  }
}

// ---------------------------------------------------------------------------
// Evidence color mapping — matches server's evidence_status_for_shot exactly
// ---------------------------------------------------------------------------

const EVIDENCE_COLORS: Record<EvidenceStatus["level"], { bg: string; border: string; label: string }> = {
  green: { bg: "#1f9d55", border: "#16803c", label: "Approved" },
  yellow: { bg: "#d4a72c", border: "#a6820f", label: "Simulation-approved" },
  red: { bg: "#c53030", border: "#9b2c2c", label: "Blocked" },
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${m.toString().padStart(2, "0")}:${s}`;
}

function getTimelineDuration(timelineArtifact?: ArtifactEnvelope<TimelineData>): number {
  if (!timelineArtifact?.present || !timelineArtifact.data) return 0;
  const shots = timelineArtifact.data.shots;
  if (shots.length === 0) return 0;
  return Math.max(...shots.map((s) => s.end));
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const PX_PER_SECOND = 40;
const TRACK_LABEL_WIDTH = 130;

export interface TimelineEditorProps {
  apiBaseUrl: string;
  projectId: string;
  /**
   * Whether shot trimming is allowed right now. This component does not
   * know NarrativeOS's stage machine — the caller (e.g. a Hermes agent
   * orchestrator, or a page that already loaded state.json) is
   * responsible for deciding this is true only during EDITORIAL_QA.
   */
  editingEnabled: boolean;
}

export const TimelineEditor: React.FC<TimelineEditorProps> = ({
  apiBaseUrl,
  projectId,
  editingEnabled,
}) => {
  const clientRef = useRef(new TimelineApiClient(apiBaseUrl));

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [shotDetail, setShotDetail] = useState<ShotEvidenceResponse | null>(null);
  const [shotDetailError, setShotDetailError] = useState<string | null>(null);

  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const [revisionInFlight, setRevisionInFlight] = useState(false);
  const [revisionError, setRevisionError] = useState<string | null>(null);

  const playbackRafRef = useRef<number | null>(null);

  const loadProject = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await clientRef.current.getProject(projectId);
      setProject(data);
    } catch (err) {
      if (err instanceof TimelineApiError) {
        setLoadError(`${err.message}${err.status === 404 ? " — project not found" : ""}`);
      } else {
        setLoadError("Unexpected error loading project");
      }
      setProject(null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  // WebSocket: reflect server-pushed revision events, reconnect on drop
  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const connect = () => {
      if (cancelled) return;
      const wsUrl = apiBaseUrl.replace(/^http/, "ws") + `/ws/timeline/${encodeURIComponent(projectId)}`;
      socket = new WebSocket(wsUrl);

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "revision_applied") {
            loadProject();
          }
        } catch {
          // Ignore malformed frames rather than crashing the UI.
        }
      };

      socket.onclose = () => {
        if (!cancelled) {
          reconnectTimer = window.setTimeout(connect, 3000);
        }
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [apiBaseUrl, projectId, loadProject]);

  const handleSelectShot = useCallback(
    async (shotId: string) => {
      setSelectedShotId(shotId);
      setShotDetail(null);
      setShotDetailError(null);
      try {
        const detail = await clientRef.current.getShotEvidence(projectId, shotId);
        setShotDetail(detail);
      } catch (err) {
        setShotDetailError(err instanceof TimelineApiError ? err.message : "Failed to load shot detail");
      }
    },
    [projectId]
  );

  const handleTrim = useCallback(
    async (shotId: string, newEnd: number, reason: string) => {
      setRevisionInFlight(true);
      setRevisionError(null);
      try {
        await clientRef.current.submitRevision(projectId, { shot_id: shotId, new_end: newEnd, reason });
        await loadProject();
        if (selectedShotId === shotId) {
          await handleSelectShot(shotId);
        }
      } catch (err) {
        if (err instanceof TimelineApiError) {
          const detail = err.detail as any;
          const message =
            typeof detail === "object" && detail?.detail
              ? typeof detail.detail === "string"
                ? detail.detail
                : JSON.stringify(detail.detail)
              : err.message;
          setRevisionError(message);
        } else {
          setRevisionError("Unexpected error submitting revision");
        }
      } finally {
        setRevisionInFlight(false);
      }
    },
    [projectId, selectedShotId, loadProject, handleSelectShot]
  );

  // Playback loop
  useEffect(() => {
    if (!isPlaying) {
      if (playbackRafRef.current !== null) {
        cancelAnimationFrame(playbackRafRef.current);
        playbackRafRef.current = null;
      }
      return;
    }

    const timeline = project?.artifacts.timeline;
    const duration = getTimelineDuration(timeline);

    let lastTs = performance.now();
    const tick = (ts: number) => {
      const dt = (ts - lastTs) / 1000;
      lastTs = ts;
      setCurrentTime((t) => {
        const next = t + dt;
        if (next >= duration) {
          setIsPlaying(false);
          return duration;
        }
        return next;
      });
      playbackRafRef.current = requestAnimationFrame(tick);
    };
    playbackRafRef.current = requestAnimationFrame(tick);

    return () => {
      if (playbackRafRef.current !== null) cancelAnimationFrame(playbackRafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPlaying]);

  if (loading) {
    return <div style={styles.centered}>Loading project…</div>;
  }

  if (loadError) {
    return (
      <div style={styles.centered}>
        <div style={styles.errorBox}>
          <strong>Could not load project.</strong>
          <div>{loadError}</div>
          <button style={styles.button} onClick={loadProject}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!project) {
    return <div style={styles.centered}>No project data.</div>;
  }

  const timelineArtifact = project.artifacts.timeline;
  if (!timelineArtifact.present || !timelineArtifact.data) {
    return (
      <div style={styles.centered}>
        <div style={styles.warnBox}>
          timeline.json is not present for project "{project.project_id}". This stage of
          NarrativeOS has not produced a timeline yet.
        </div>
      </div>
    );
  }

  const timeline: TimelineData = timelineArtifact.data;
  const duration = getTimelineDuration(timelineArtifact);

  return (
    <div style={styles.container}>
      <Header
        project={project}
        isPlaying={isPlaying}
        onTogglePlay={() => setIsPlaying((p) => !p)}
        onReset={() => setCurrentTime(0)}
      />

      <MissingArtifactsBanner artifacts={project.artifacts} />

      <div style={styles.metaRow}>
        <MetaItem label="Playhead" value={formatTime(currentTime)} mono />
        <MetaItem label="Duration" value={formatTime(duration)} mono />
        <MetaItem label="Shots" value={String(timeline.shots.length)} />
        <MetaItem
          label="Events log"
          value={project.events.present ? `${project.events.items.length} entries` : "not present"}
        />
      </div>

      <div style={styles.timelineScroll}>
        <TrackRuler duration={duration} />
        <VideoTrack
          shots={timeline.shots}
          evidenceByShot={project.evidence_by_shot}
          selectedShotId={selectedShotId}
          onSelect={handleSelectShot}
        />
        <Playhead currentTime={currentTime} />
      </div>

      {selectedShotId && (
        <ShotDetailPanel
          shotId={selectedShotId}
          detail={shotDetail}
          error={shotDetailError}
          editingEnabled={editingEnabled}
          onTrim={handleTrim}
          revisionInFlight={revisionInFlight}
          revisionError={revisionError}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

const Header: React.FC<{
  project: ProjectResponse;
  isPlaying: boolean;
  onTogglePlay: () => void;
  onReset: () => void;
}> = ({ project, isPlaying, onTogglePlay, onReset }) => {
  const isSimulation = project.artifacts.integration_report?.present ?? false;
  return (
    <div style={styles.header}>
      <div>
        <h2 style={styles.title}>Timeline — {project.project_id}</h2>
        {isSimulation && (
          <div style={styles.simulationTag}>
            SIMULATION PROJECT — production_ready is false in integration_report.json
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button style={styles.button} onClick={onTogglePlay}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button style={styles.buttonSecondary} onClick={onReset}>
          Reset
        </button>
      </div>
    </div>
  );
};

const MissingArtifactsBanner: React.FC<{ artifacts: Record<string, ArtifactEnvelope<any>> }> = ({
  artifacts,
}) => {
  const missing = Object.entries(artifacts)
    .filter(([, v]) => !v.present)
    .map(([k]) => k);

  if (missing.length === 0) return null;

  return <div style={styles.missingBanner}>Not present in this project: {missing.join(", ")}</div>;
};

const MetaItem: React.FC<{ label: string; value: string; mono?: boolean }> = ({ label, value, mono }) => (
  <div style={styles.metaItem}>
    <div style={styles.metaLabel}>{label}</div>
    <div style={{ ...styles.metaValue, fontFamily: mono ? "monospace" : undefined }}>{value}</div>
  </div>
);

const TrackRuler: React.FC<{ duration: number }> = ({ duration }) => {
  const marks = Math.ceil(duration) + 1;
  return (
    <div style={styles.ruler}>
      <div style={{ width: TRACK_LABEL_WIDTH, flexShrink: 0 }} />
      <div style={{ display: "flex" }}>
        {Array.from({ length: marks }).map((_, i) => (
          <span key={i} style={{ width: PX_PER_SECOND, fontSize: 10, color: "#888" }}>
            {i}s
          </span>
        ))}
      </div>
    </div>
  );
};

const VideoTrack: React.FC<{
  shots: Shot[];
  evidenceByShot: Record<string, EvidenceStatus>;
  selectedShotId: string | null;
  onSelect: (shotId: string) => void;
}> = ({ shots, evidenceByShot, selectedShotId, onSelect }) => (
  <div style={styles.trackRow}>
    <div style={styles.trackLabel}>Video</div>
    <div style={{ position: "relative", height: 56, flex: 1 }}>
      {shots.map((shot) => {
        const evidence = evidenceByShot[shot.shot_id];
        const colors = evidence ? EVIDENCE_COLORS[evidence.level] : EVIDENCE_COLORS.red;
        const width = Math.max(4, (shot.end - shot.start) * PX_PER_SECOND);
        const left = shot.start * PX_PER_SECOND;
        const isSelected = shot.shot_id === selectedShotId;
        return (
          <button
            key={shot.shot_id}
            onClick={() => onSelect(shot.shot_id)}
            title={`${shot.shot_id} — ${colors.label}${evidence ? `: ${evidence.reasons.join(", ")}` : ""}`}
            style={{
              position: "absolute",
              left,
              width,
              top: 4,
              height: 48,
              background: colors.bg,
              border: isSelected ? "2px solid #fff" : `1px solid ${colors.border}`,
              borderRadius: 4,
              color: "#fff",
              fontSize: 11,
              padding: 4,
              cursor: "pointer",
              overflow: "hidden",
              textAlign: "left",
            }}
          >
            {shot.shot_id}
          </button>
        );
      })}
    </div>
  </div>
);

const Playhead: React.FC<{ currentTime: number }> = ({ currentTime }) => (
  <div
    style={{
      position: "absolute",
      left: TRACK_LABEL_WIDTH + currentTime * PX_PER_SECOND,
      top: 0,
      bottom: 0,
      width: 2,
      background: "#fff",
      pointerEvents: "none",
    }}
  />
);

const ShotDetailPanel: React.FC<{
  shotId: string;
  detail: ShotEvidenceResponse | null;
  error: string | null;
  editingEnabled: boolean;
  onTrim: (shotId: string, newEnd: number, reason: string) => void;
  revisionInFlight: boolean;
  revisionError: string | null;
}> = ({ shotId, detail, error, editingEnabled, onTrim, revisionInFlight, revisionError }) => {
  const [trimSeconds, setTrimSeconds] = useState(1);
  const [reason, setReason] = useState("");

  if (error) {
    return <div style={{ ...styles.panel, ...styles.errorBox }}>{error}</div>;
  }

  if (!detail) {
    return <div style={styles.panel}>Loading shot {shotId}…</div>;
  }

  const colors = EVIDENCE_COLORS[detail.evidence.level];

  return (
    <div style={styles.panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>{detail.shot_id}</h3>
        <span style={{ ...styles.badge, background: colors.bg }}>{colors.label}</span>
      </div>

      {detail.evidence.reasons.length > 0 && (
        <ul style={styles.reasonList}>
          {detail.evidence.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}

      <dl style={styles.dl}>
        <dt>Asset</dt>
        <dd>{detail.shot.asset_id}</dd>
        <dt>Timing</dt>
        <dd>
          {formatTime(detail.shot.start)} → {formatTime(detail.shot.end)}
        </dd>
        <dt>Motion / transition</dt>
        <dd>
          {detail.shot.motion} / {detail.shot.transition}
        </dd>
        {detail.evidence.usable_interval && (
          <>
            <dt>Usable source interval</dt>
            <dd>
              {detail.evidence.usable_interval[0]}s – {detail.evidence.usable_interval[1]}s
            </dd>
          </>
        )}
      </dl>

      {detail.shot_spec.present && detail.shot_spec.data && (
        <>
          <h4 style={styles.sectionTitle}>Shot spec</h4>
          <dl style={styles.dl}>
            <dt>Narration</dt>
            <dd>{detail.shot_spec.data.narration || "—"}</dd>
            <dt>Visual purpose</dt>
            <dd>{detail.shot_spec.data.visual_purpose || "—"}</dd>
          </dl>
        </>
      )}

      {detail.claims.length > 0 && (
        <>
          <h4 style={styles.sectionTitle}>Supporting claims</h4>
          <ul style={styles.plainList}>
            {detail.claims.map((c) => (
              <li key={c.claim_id}>{c.text || c.claim_id}</li>
            ))}
          </ul>
        </>
      )}

      {detail.overlapping_audio_events.length > 0 && (
        <>
          <h4 style={styles.sectionTitle}>Audio events</h4>
          <ul style={styles.plainList}>
            {detail.overlapping_audio_events.map((e, i) => (
              <li key={i}>
                {e.type} ({e.start}s{e.end ? `–${e.end}s` : ""})
              </li>
            ))}
          </ul>
        </>
      )}

      {editingEnabled ? (
        <div style={styles.editBox}>
          <h4 style={styles.sectionTitle}>Trim shot end</h4>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="number"
              step={0.5}
              value={trimSeconds}
              onChange={(e) => setTrimSeconds(parseFloat(e.target.value) || 0)}
              style={styles.input}
            />
            <span>seconds off the end</span>
          </div>
          <input
            type="text"
            placeholder="Reason for this revision (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ ...styles.input, width: "100%", marginTop: 8 }}
          />
          <button
            style={styles.button}
            disabled={revisionInFlight || !reason.trim()}
            onClick={() => onTrim(shotId, Math.max(0, detail.shot.end - trimSeconds), reason.trim())}
          >
            {revisionInFlight ? "Applying…" : "Apply trim"}
          </button>
          {revisionError && <div style={styles.errorBox}>{revisionError}</div>}
        </div>
      ) : (
        <div style={styles.readOnlyNote}>
          Editing is disabled for this view. Timing changes are only accepted during
          EDITORIAL_QA, and this is enforced by whoever hosts this component, not by
          the component itself.
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Styles — inline, no external stylesheet dependency
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  container: { display: "flex", flexDirection: "column", gap: 12, fontFamily: "system-ui, sans-serif" },
  centered: { display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200 },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" },
  title: { margin: 0, fontSize: 16, fontWeight: 600 },
  simulationTag: {
    marginTop: 4,
    fontSize: 11,
    color: "#d4a72c",
    fontWeight: 600,
    letterSpacing: 0.3,
  },
  missingBanner: {
    fontSize: 12,
    color: "#a0aec0",
    background: "#1a202c",
    padding: "6px 10px",
    borderRadius: 4,
  },
  metaRow: { display: "flex", gap: 16 },
  metaItem: { flex: 1 },
  metaLabel: { fontSize: 11, color: "#888" },
  metaValue: { fontSize: 14, fontWeight: 500 },
  timelineScroll: {
    position: "relative",
    border: "1px solid #333",
    borderRadius: 6,
    overflowX: "auto",
    padding: "8px 0",
  },
  ruler: { display: "flex", paddingLeft: 0, marginBottom: 4 },
  trackRow: { display: "flex", alignItems: "center", minHeight: 60 },
  trackLabel: { width: TRACK_LABEL_WIDTH, flexShrink: 0, fontSize: 12, color: "#ccc", paddingLeft: 8 },
  panel: { border: "1px solid #333", borderRadius: 6, padding: 16 },
  badge: { padding: "2px 10px", borderRadius: 12, fontSize: 11, color: "#fff", fontWeight: 600 },
  reasonList: { margin: "8px 0", paddingLeft: 20, fontSize: 12, color: "#e08080" },
  dl: { display: "grid", gridTemplateColumns: "160px 1fr", rowGap: 4, fontSize: 13, margin: "8px 0" },
  sectionTitle: { fontSize: 13, marginTop: 16, marginBottom: 4, color: "#aaa" },
  plainList: { margin: 0, paddingLeft: 20, fontSize: 13 },
  editBox: { marginTop: 16, paddingTop: 12, borderTop: "1px solid #333" },
  input: { padding: 6, borderRadius: 4, border: "1px solid #444", background: "#1a1a1a", color: "#fff" },
  button: {
    padding: "8px 14px",
    borderRadius: 4,
    border: "none",
    background: "#3182ce",
    color: "#fff",
    cursor: "pointer",
    fontSize: 13,
  },
  buttonSecondary: {
    padding: "8px 14px",
    borderRadius: 4,
    border: "1px solid #444",
    background: "transparent",
    color: "#ccc",
    cursor: "pointer",
    fontSize: 13,
  },
  errorBox: {
    background: "#2d1414",
    border: "1px solid #9b2c2c",
    borderRadius: 4,
    padding: 10,
    fontSize: 12,
    color: "#feb2b2",
  },
  warnBox: {
    background: "#2d2410",
    border: "1px solid #a6820f",
    borderRadius: 4,
    padding: 10,
    fontSize: 13,
    color: "#f6e05e",
  },
  readOnlyNote: {
    marginTop: 16,
    paddingTop: 12,
    borderTop: "1px solid #333",
    fontSize: 12,
    color: "#888",
    fontStyle: "italic",
  },
};

export default TimelineEditor;
