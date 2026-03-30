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

export type PickedDocument = {
  sourcePath: string;
  filename: string;
};

export interface AppService {
  loadModelConfig(): Promise<ModelConfig>;
  saveModelConfig(config: ModelConfig): Promise<ModelConfig>;
  testModelConnection(config: ModelConfig): Promise<TestConnectionResult>;
  pickInputFile(): Promise<PickedDocument | null>;
  getDocumentStatus(sourcePath: string, modelConfig: ModelConfig): Promise<DocumentStatus>;
  getDocumentHistory(sourcePath: string): Promise<DocumentHistory>;
  listDocumentHistories(): Promise<HistoryListResponse>;
  deleteDocumentHistory(docId: string, fromRound?: number): Promise<DeleteHistoryResult>;
  startRunRound(sourcePath: string, modelConfig: ModelConfig): Promise<string | null>;
  awaitRunRound(sourcePath: string, modelConfig: ModelConfig, runToken?: string | null): Promise<RoundResult>;
  listenRoundProgress(onProgress: (payload: RoundProgress) => void, runToken?: string | null): Promise<() => void>;
  readOutput(outputPath: string): Promise<{ path: string; text: string }>;
  exportRound(outputPath: string, targetFormat: "txt" | "docx"): Promise<ExportResult>;
}