import type { AppService, PickedDocument } from "./appService";
import type {
  DeleteHistoryResult,
  DocumentHistory,
  DocumentStatus,
  ExportResult,
  HistoryListResponse,
  ModelConfig,
  RoundProgress,
  RoundResult,
  TestConnectionResult,
} from "../types/app";

const WEB_API_BASE = (globalThis as { __BAIBAIAIGC_WEB_API__?: string }).__BAIBAIAIGC_WEB_API__ ?? "";

const defaultModelConfig: ModelConfig = {
  baseUrl: "",
  apiKey: "",
  model: "",
  apiType: "chat_completions",
  temperature: 0.7,
  offlineMode: false,
};

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

export const webService: AppService = {
  async loadModelConfig(): Promise<ModelConfig> {
    const config = await requestJson<Partial<ModelConfig>>("/api/model-config");
    return { ...defaultModelConfig, ...config };
  },

  async saveModelConfig(config: ModelConfig): Promise<ModelConfig> {
    const saved = await requestJson<Partial<ModelConfig>>("/api/model-config", {
      method: "POST",
      body: JSON.stringify(config),
    });
    return { ...defaultModelConfig, ...saved };
  },

  async testModelConnection(config: ModelConfig): Promise<TestConnectionResult> {
    return requestJson<TestConnectionResult>("/api/test-connection", {
      method: "POST",
      body: JSON.stringify(config),
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
          const requestBody = lowerName.endsWith(".docx")
            ? {
                filename: file.name,
                encoding: "base64",
                contentBase64: await readFileAsBase64(file),
              }
            : {
                filename: file.name,
                encoding: "text",
                content: await readFileWithFallback(file),
              };
          const payload = await requestJson<PickedDocument>("/api/upload-document", {
            method: "POST",
            body: JSON.stringify(requestBody),
          });
          resolve(payload);
        } catch (error) {
          reject(error);
        }
      }, { once: true });
      input.click();
    });
  },

  async getDocumentStatus(sourcePath: string): Promise<DocumentStatus> {
    return requestJson<DocumentStatus>(`/api/document-status?sourcePath=${encodeURIComponent(sourcePath)}`);
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

  async startRunRound(sourcePath: string, modelConfig: ModelConfig): Promise<string | null> {
    const { runId } = await requestJson<{ runId: string }>("/api/run-round", {
      method: "POST",
      body: JSON.stringify({ sourcePath, modelConfig }),
    });
    return runId;
  },

  async awaitRunRound(_: string, __: ModelConfig, runToken?: string | null): Promise<RoundResult> {
    if (!runToken) {
      throw new Error("runToken is required in web mode.");
    }
    return new Promise<RoundResult>((resolve, reject) => {
      const eventSource = new EventSource(`${WEB_API_BASE}/api/run-round-events/${runToken}`);
      eventSource.addEventListener("result", (event) => {
        eventSource.close();
        resolve(JSON.parse((event as MessageEvent).data) as RoundResult);
      });
      eventSource.addEventListener("error", (event) => {
        eventSource.close();
        const payload = JSON.parse((event as MessageEvent).data) as { message?: string };
        reject(new Error(payload.message || "Run round failed."));
      });
      eventSource.onerror = () => {
        eventSource.close();
        reject(new Error("Progress channel disconnected."));
      };
    });
  },

  async listenRoundProgress(onProgress: (payload: RoundProgress) => void, runToken?: string | null): Promise<() => void> {
    if (!runToken) {
      return async () => undefined;
    }
    const eventSource = new EventSource(`${WEB_API_BASE}/api/run-round-events/${runToken}`);
    const handler = (event: Event) => {
      const message = event as MessageEvent;
      onProgress(JSON.parse(message.data) as RoundProgress);
    };
    eventSource.addEventListener("progress", handler);
    return async () => {
      eventSource.close();
    };
  },

  async readOutput(outputPath: string): Promise<{ path: string; text: string }> {
    return requestJson<{ path: string; text: string }>(`/api/read-output?outputPath=${encodeURIComponent(outputPath)}`);
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
};