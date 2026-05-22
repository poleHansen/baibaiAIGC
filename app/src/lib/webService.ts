import type { AppService, PickedDocument, ReduceTextResult } from "./appService";
import { normalizeModelConfig } from "../types/app";
import type {
  DeleteHistoryResult,
  DocumentHistory,
  DocumentStatus,
  ExportResult,
  HistoryListResponse,
  ModelConfig,
  OutputPreview,
  RoundProgress,
  RoundResult,
  RunExecutionOptions,
  TestConnectionResult,
} from "../types/app";

const WEB_API_BASE = (globalThis as { __BAIBAIAIGC_WEB_API__?: string }).__BAIBAIAIGC_WEB_API__ ?? "";

type ProgressListener = (payload: RoundProgress) => void;

type RunStream = {
  progressListeners: Set<ProgressListener>;
  resultPromise: Promise<RoundResult>;
  close: () => void;
};

type ReduceTextStream = {
  progressListeners: Set<ProgressListener>;
  resultPromise: Promise<ReduceTextResult>;
  close: () => void;
};

type UploadDocumentResponse = PickedDocument & {
  conflict?: boolean;
  reused?: boolean;
};

const runStreams = new Map<string, RunStream>();
const reduceTextStreams = new Map<string, ReduceTextStream>();

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${WEB_API_BASE}${input}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const errorPayload = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(errorPayload?.message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function readFileWithFallback(file: File): Promise<string> {
  if (file.name.toLowerCase().endsWith(".txt")) {
    return file.text();
  }
  throw new Error("Unsupported text read for current file type.");
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Failed to read file."));
        return;
      }
      const commaIndex = result.indexOf(",");
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.onerror = () => reject(new Error("Failed to read file."));
    reader.readAsDataURL(file);
  });
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function parseMessageEvent<T>(event: Event, fallbackMessage: string): T {
  if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
    throw new Error(fallbackMessage);
  }
  return JSON.parse(event.data) as T;
}

function createRunStream(runToken: string): RunStream {
  let closed = false;
  let settled = false;
  let resolveResult!: (value: RoundResult) => void;
  let rejectResult!: (reason: Error) => void;

  const progressListeners = new Set<ProgressListener>();
  const eventSource = new EventSource(`${WEB_API_BASE}/api/run-round-events/${runToken}`);

  const close = () => {
    if (closed) {
      return;
    }
    closed = true;
    eventSource.close();
    runStreams.delete(runToken);
  };

  const settleResult = (value: RoundResult) => {
    if (settled) {
      return;
    }
    settled = true;
    resolveResult(value);
    close();
  };

  const settleError = (message: string) => {
    if (settled) {
      return;
    }
    settled = true;
    rejectResult(new Error(message));
    close();
  };

  const resultPromise = new Promise<RoundResult>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject as (reason: Error) => void;
  });

  eventSource.addEventListener("progress", (event) => {
    try {
      const payload = parseMessageEvent<RoundProgress>(event, "Invalid progress event.");
      progressListeners.forEach((listener) => listener(payload));
    } catch (error) {
      settleError(error instanceof Error ? error.message : "Invalid progress event.");
    }
  });

  eventSource.addEventListener("result", (event) => {
    try {
      settleResult(parseMessageEvent<RoundResult>(event, "Invalid run result."));
    } catch (error) {
      settleError(error instanceof Error ? error.message : "Invalid run result.");
    }
  });

  eventSource.addEventListener("error", (event) => {
    if (!(event instanceof MessageEvent) || typeof event.data !== "string") {
      return;
    }
    try {
      const payload = JSON.parse(event.data) as { message?: string };
      settleError(payload.message || "Run round failed.");
    } catch {
      settleError("Run round failed.");
    }
  });

  eventSource.onerror = () => {
    settleError("Progress channel disconnected.");
  };

  return {
    progressListeners,
    resultPromise,
    close,
  };
}

function getRunStream(runToken: string): RunStream {
  const existing = runStreams.get(runToken);
  if (existing) {
    return existing;
  }
  const stream = createRunStream(runToken);
  runStreams.set(runToken, stream);
  return stream;
}

function createReduceTextStream(runToken: string): ReduceTextStream {
  let closed = false;
  let settled = false;
  let resolveResult!: (value: ReduceTextResult) => void;
  let rejectResult!: (reason: Error) => void;

  const progressListeners = new Set<ProgressListener>();
  const eventSource = new EventSource(`${WEB_API_BASE}/api/run-round-events/${runToken}`);

  const close = () => {
    if (closed) return;
    closed = true;
    eventSource.close();
    reduceTextStreams.delete(runToken);
  };

  const settleResult = (value: ReduceTextResult) => {
    if (settled) return;
    settled = true;
    resolveResult(value);
    close();
  };

  const settleError = (message: string) => {
    if (settled) return;
    settled = true;
    rejectResult(new Error(message));
    close();
  };

  const resultPromise = new Promise<ReduceTextResult>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject as (reason: Error) => void;
  });

  eventSource.addEventListener("progress", (event) => {
    try {
      const payload = parseMessageEvent<RoundProgress>(event, "Invalid progress event.");
      progressListeners.forEach((listener) => listener(payload));
    } catch (error) {
      settleError(error instanceof Error ? error.message : "Invalid progress event.");
    }
  });

  eventSource.addEventListener("result", (event) => {
    try {
      settleResult(parseMessageEvent<ReduceTextResult>(event, "Invalid reduce text result."));
    } catch (error) {
      settleError(error instanceof Error ? error.message : "Invalid reduce text result.");
    }
  });

  eventSource.addEventListener("error", (event) => {
    if (!(event instanceof MessageEvent) || typeof event.data !== "string") return;
    try {
      const payload = JSON.parse(event.data) as { message?: string };
      settleError(payload.message || "Reduce text failed.");
    } catch {
      settleError("Reduce text failed.");
    }
  });

  eventSource.onerror = () => {
    settleError("Progress channel disconnected.");
  };

  return { progressListeners, resultPromise, close };
}

function getReduceTextStream(runToken: string): ReduceTextStream {
  const existing = reduceTextStreams.get(runToken);
  if (existing) return existing;
  const stream = createReduceTextStream(runToken);
  reduceTextStreams.set(runToken, stream);
  return stream;
}

export const webService: AppService = {
  async loadModelConfig(): Promise<ModelConfig> {
    const config = await requestJson<Partial<ModelConfig>>("/api/model-config");
    return normalizeModelConfig(config);
  },

  async saveModelConfig(config: ModelConfig): Promise<ModelConfig> {
    const saved = await requestJson<Partial<ModelConfig>>("/api/model-config", {
      method: "POST",
      body: JSON.stringify(normalizeModelConfig(config)),
    });
    return normalizeModelConfig(saved);
  },

  async testModelConnection(config: ModelConfig): Promise<TestConnectionResult> {
    return requestJson<TestConnectionResult>("/api/test-connection", {
      method: "POST",
      body: JSON.stringify(normalizeModelConfig(config)),
    });
  },

  async pickInputFile(): Promise<PickedDocument | null> {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".txt,.docx";
    return new Promise((resolve, reject) => {
      input.addEventListener("change", async () => {
        const file = input.files?.[0];
        if (!file) {
          resolve(null);
          return;
        }
        try {
          const lowerName = file.name.toLowerCase();
          const buildRequestBody = async (duplicateAction?: "reuse_existing" | "replace_with_new") => {
            if (lowerName.endsWith(".docx")) {
              return {
                filename: file.name,
                encoding: "base64",
                contentBase64: await readFileAsBase64(file),
                duplicateAction: duplicateAction ?? null,
              };
            }
            return {
              filename: file.name,
              encoding: "text",
              content: await readFileWithFallback(file),
              duplicateAction: duplicateAction ?? null,
            };
          };

          const upload = async (duplicateAction?: "reuse_existing" | "replace_with_new") => requestJson<UploadDocumentResponse>("/api/upload-document", {
            method: "POST",
            body: JSON.stringify(await buildRequestBody(duplicateAction)),
          });

          let payload = await upload();
          if (payload.conflict) {
            const reuseExisting = globalThis.confirm("检测到同名文件。选择“确定”使用以前的文件，选择“取消”重新上传新文件。");
            payload = await upload(reuseExisting ? "reuse_existing" : "replace_with_new");
          }
          resolve(payload);
        } catch (error) {
          reject(error);
        }
      }, { once: true });
      input.click();
    });
  },

  async getDocumentStatus(sourcePath: string, modelConfig: ModelConfig): Promise<DocumentStatus> {
    return requestJson<DocumentStatus>(
      `/api/document-status?sourcePath=${encodeURIComponent(sourcePath)}&promptProfile=${encodeURIComponent(modelConfig.promptProfile)}`,
    );
  },

  async getDocumentHistory(sourcePath: string): Promise<DocumentHistory> {
    return requestJson<DocumentHistory>(`/api/document-history?sourcePath=${encodeURIComponent(sourcePath)}`);
  },

  async listDocumentHistories(): Promise<HistoryListResponse> {
    return requestJson<HistoryListResponse>("/api/history-documents");
  },

  async deleteDocumentHistory(docId: string, fromRound?: number): Promise<DeleteHistoryResult> {
    return requestJson<DeleteHistoryResult>("/api/document-history", {
      method: "DELETE",
      body: JSON.stringify({ docId, fromRound: fromRound ?? null }),
    });
  },

  async requestStop(sourcePath: string, modelConfig: ModelConfig): Promise<DocumentStatus> {
    return requestJson<DocumentStatus>("/api/request-stop", {
      method: "POST",
      body: JSON.stringify({ sourcePath, promptProfile: modelConfig.promptProfile }),
    });
  },

  async startRunRound(sourcePath: string, modelConfig: ModelConfig, executionOptions?: RunExecutionOptions | null): Promise<string | null> {
    const { runId } = await requestJson<{ runId: string }>("/api/run-round", {
      method: "POST",
      body: JSON.stringify({
        sourcePath,
        modelConfig: normalizeModelConfig(modelConfig),
        executionOptions: executionOptions ?? null,
      }),
    });
    return runId;
  },

  async awaitRunRound(_sourcePath: string, _modelConfig: ModelConfig, runToken?: string | null, _executionOptions?: RunExecutionOptions | null): Promise<RoundResult> {
    if (!runToken) {
      throw new Error("runToken is required in web mode.");
    }
    return getRunStream(runToken).resultPromise;
  },

  async listenRoundProgress(onProgress: (payload: RoundProgress) => void, runToken?: string | null): Promise<() => void> {
    if (!runToken) {
      return () => undefined;
    }
    const stream = getRunStream(runToken);
    stream.progressListeners.add(onProgress);
    return () => {
      stream.progressListeners.delete(onProgress);
    };
  },

  async readOutput(outputPath: string): Promise<{ path: string; text: string }> {
    return requestJson<{ path: string; text: string }>(`/api/read-output?outputPath=${encodeURIComponent(outputPath)}`);
  },

  async readOutputPreview(outputPath: string, manifestPath: string): Promise<OutputPreview> {
    return requestJson<OutputPreview>(
      `/api/read-output-preview?outputPath=${encodeURIComponent(outputPath)}&manifestPath=${encodeURIComponent(manifestPath)}`,
    );
  },

  async readSourcePreview(inputPath: string, manifestPath: string, promptProfile: "cn" | "en"): Promise<OutputPreview> {
    return requestJson<OutputPreview>(
      `/api/read-source-preview?inputPath=${encodeURIComponent(inputPath)}&manifestPath=${encodeURIComponent(manifestPath)}&promptProfile=${encodeURIComponent(promptProfile)}`,
    );
  },

  async exportRound(outputPath: string, targetFormat: "txt" | "docx"): Promise<ExportResult> {
    const response = await fetch(
      `${WEB_API_BASE}/api/export-round?outputPath=${encodeURIComponent(outputPath)}&targetFormat=${targetFormat}`,
    );
    if (!response.ok) {
      throw new Error(`Export failed: ${response.status}`);
    }
    const blob = await response.blob();
    const filename = decodeURIComponent(
      response.headers.get("Content-Disposition")?.match(/filename="?([^\"]+)"?/)?.[1] ?? `当前轮结果.${targetFormat}`,
    );
    downloadBlob(blob, filename);
    return {
      format: targetFormat,
      path: filename,
    };
  },

  async startReduceText(text: string, modelConfig: ModelConfig): Promise<string | null> {
    const { runId } = await requestJson<{ runId: string }>("/api/reduce-text", {
      method: "POST",
      body: JSON.stringify({ text, modelConfig: normalizeModelConfig(modelConfig) }),
    });
    return runId;
  },

  async awaitReduceText(runToken?: string | null): Promise<ReduceTextResult> {
    if (!runToken) {
      throw new Error("runToken is required in web mode.");
    }
    return getReduceTextStream(runToken).resultPromise;
  },
};
