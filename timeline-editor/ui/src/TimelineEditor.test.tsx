/**
 * Tests for TimelineEditor.tsx
 *
 * Fixtures in __fixtures__/ are NOT hand-written. They were captured by
 * calling the real timeline_api_server.py TestClient against real output
 * of scripts/simulate_documentary.py (see the repo's Python test suite,
 * timeline-editor/tests/test_timeline_api_server.py, for the equivalent
 * server-side assertions). If the API response shape drifts, these
 * fixtures need to be regenerated — that is the point: this test suite
 * fails loudly on schema drift instead of silently passing against a
 * fixture that no longer matches reality.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TimelineEditor } from "./TimelineEditor";

import projectResponseFixture from "./__fixtures__/project_response.json";
import evidenceResponseFixture from "./__fixtures__/evidence_response.json";

const API_BASE = "http://localhost:8420";

function mockFetchSequence(responses: Array<{ url: RegExp; body: unknown; status?: number }>) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const match = responses.find((r) => r.url.test(url));
    if (!match) {
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ detail: `no mock for ${url}` }),
        text: () => Promise.resolve(`no mock for ${url}`),
      } as Response);
    }
    return Promise.resolve({
      ok: (match.status ?? 200) < 400,
      status: match.status ?? 200,
      json: () => Promise.resolve(match.body),
      text: () => Promise.resolve(JSON.stringify(match.body)),
    } as Response);
  }) as jest.Mock;
}

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  send() {}
}

beforeEach(() => {
  MockWebSocket.instances = [];
  // @ts-expect-error test double replacing the real WebSocket global
  global.WebSocket = MockWebSocket;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("TimelineEditor loading states", () => {
  test("shows loading indicator before data arrives", async () => {
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: projectResponseFixture }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);
    expect(screen.getByText(/Loading project/i)).toBeInTheDocument();
    // Let the in-flight fetch resolve before the test exits, so the
    // resulting state update happens inside this test's act() scope
    // instead of leaking into whichever test runs next.
    await waitFor(() => expect(screen.getByText(/Timeline — demo/)).toBeInTheDocument());
  });

  test("renders timeline once real project data loads", async () => {
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: projectResponseFixture }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText(/Timeline — demo/)).toBeInTheDocument());

    // The real fixture has shots B001 and B002.
    expect(screen.getByText("B001")).toBeInTheDocument();
    expect(screen.getByText("B002")).toBeInTheDocument();
  });

  test("shows the simulation banner because integration_report.json is present in the fixture", async () => {
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: projectResponseFixture }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() =>
      expect(screen.getByText(/SIMULATION PROJECT/)).toBeInTheDocument()
    );
  });

  test("lists artifacts that are genuinely absent in the real fixture (assets.json, events.jsonl-derived state)", async () => {
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: projectResponseFixture }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText(/Not present in this project/)).toBeInTheDocument());
    // Confirmed absent by the real server run captured in the fixture.
    expect(screen.getByText(/assets/)).toBeInTheDocument();
  });

  test("shows an error state and retry button when the project fetch fails", async () => {
    mockFetchSequence([{ url: /\/api\/project\/missing$/, body: { detail: "not found" }, status: 404 }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="missing" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText(/Could not load project/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

describe("TimelineEditor evidence display", () => {
  test("shots are marked red/blocked, matching the real evidence_by_shot in the fixture", async () => {
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: projectResponseFixture }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText("B001")).toBeInTheDocument());

    const shotButton = screen.getByText("B001").closest("button");
    expect(shotButton).not.toBeNull();
    expect(shotButton).toHaveAttribute("title", expect.stringContaining("Blocked"));
    expect(shotButton).toHaveAttribute("title", expect.stringContaining("insufficient_evidence_frames"));
  });

  test("clicking a shot loads and displays its real evidence detail", async () => {
    mockFetchSequence([
      { url: /\/api\/project\/demo$/, body: projectResponseFixture },
      { url: /\/evidence\/B001$/, body: evidenceResponseFixture },
    ]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText("B001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /B001/i }));

    await waitFor(() => expect(screen.getByText(/insufficient_evidence_frames/)).toBeInTheDocument());
  });

  test("editing controls are hidden when editingEnabled is false, regardless of evidence status", async () => {
    mockFetchSequence([
      { url: /\/api\/project\/demo$/, body: projectResponseFixture },
      { url: /\/evidence\/B001$/, body: evidenceResponseFixture },
    ]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() => expect(screen.getByText("B001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /B001/i }));

    await waitFor(() => expect(screen.getByText(/Editing is disabled/)).toBeInTheDocument());
    expect(screen.queryByText(/Apply trim/)).not.toBeInTheDocument();
  });

  test("editing controls appear when editingEnabled is true", async () => {
    mockFetchSequence([
      { url: /\/api\/project\/demo$/, body: projectResponseFixture },
      { url: /\/evidence\/B001$/, body: evidenceResponseFixture },
    ]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={true} />);

    await waitFor(() => expect(screen.getByText("B001")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /B001/i }));

    await waitFor(() => expect(screen.getByText(/Apply trim/)).toBeInTheDocument());
  });
});

describe("TimelineEditor missing timeline.json", () => {
  test("shows an explicit message rather than crashing when timeline is absent", async () => {
    const withoutTimeline = {
      ...projectResponseFixture,
      artifacts: {
        ...projectResponseFixture.artifacts,
        timeline: { present: false, data: null },
      },
    };
    mockFetchSequence([{ url: /\/api\/project\/demo$/, body: withoutTimeline }]);
    render(<TimelineEditor apiBaseUrl={API_BASE} projectId="demo" editingEnabled={false} />);

    await waitFor(() =>
      expect(screen.getByText(/timeline\.json is not present/)).toBeInTheDocument()
    );
  });
});
