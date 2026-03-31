import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
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

const defaultModelConfig: ModelConfig = {
  baseUrl: "",
  apiKey: "",
  model: "",
  apiType: "responses",
  temperature: 0.7,
  offlineMode: false,
  promptProfile: "cn",
};

export const desktopService: AppService = {
  async loadModelConfig(): Promise<ModelConfig> {
    const config = await invoke<Partial<ModelConfig>>("load_model_config");
    return { ...defaultModelConfig, ...config };
  },

  async saveModelConfig(config: ModelConfig): Promise<ModelConfig> {
    const saved = await invoke<Partial<ModelConfig>>("save_model_config", { config });
    return { ...defaultModelConfig, ...saved };
  },

  async testModelConnection(config: ModelConfig): Promise<TestConnectionResult> {
    return invoke<TestConnectionResult>("test_model_connection", { config });
  },

  async pickInputFile(): Promise<PickedDocument | null> {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "Documents", extensions: ["txt", "docx"] }],
    });
    if (typeof selected !== "string") {
      return null;
    }
    return {
      sourcePath: selected,
      filename: selected.split(/[/\\]/).pop() ?? selected,
    };
  },

  async getDocumentStatus(sourcePath: string, modelConfig: ModelConfig): Promise<DocumentStatus> {
    return invoke<DocumentStatus>("get_document_status", { sourcePath, promptProfile: modelConfig.promptProfile });
  },

  async getDocumentHistory(sourcePath: string): Promise<DocumentHistory> {
    return invoke<DocumentHistory>("get_document_history", { sourcePath });
  },

  async listDocumentHistories(): Promise<HistoryListResponse> {
    return invoke<HistoryListResponse>("list_document_histories");
  },

  async deleteDocumentHistory(docId: string, fromRound?: number): Promise<DeleteHistoryResult> {
    return invoke<DeleteHistoryResult>("delete_document_history", { docId, fromRound: fromRound ?? null });
  },

  async startRunRound(): Promise<string | null> {
    return null;
  },

  async awaitRunRound(sourcePath: string, modelConfig: ModelConfig): Promise<RoundResult> {
    return invoke<RoundResult>("run_aigc_round", { sourcePath, modelConfig });
  },

  async listenRoundProgress(onProgress: (payload: RoundProgress) => void): Promise<UnlistenFn> {
    return listen<RoundProgress>("round-progress", (event) => {
      onProgress(event.payload);
    });
  },

  async readOutput(outputPath: string): Promise<{ path: string; text: string }> {
    return invoke<{ path: string; text: string }>("read_output_text", { outputPath });
  },

  async exportRound(outputPath: string, targetFormat: "txt" | "docx"): Promise<ExportResult> {
    const exportPath = await save({
      defaultPath: targetFormat === "docx" ? "当前轮结果.docx" : "当前轮结果.txt",
      filters: [{ name: "Export", extensions: [targetFormat] }],
    });
    if (!exportPath || Array.isArray(exportPath)) {
      throw new Error("Export cancelled");
    }
    return invoke<ExportResult>("export_round_output", { outputPath, exportPath, targetFormat });
  },
};