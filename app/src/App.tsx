import { useEffect, useRef, useState } from "react";
import { DocumentCard } from "./components/DocumentCard";
import { HistoryCard } from "./components/HistoryCard";
import { ModelConfigCard } from "./components/ModelConfigCard";
import { ResultCard } from "./components/ResultCard";
import { TextReduceCard } from "./components/TextReduceCard";
import { useAppState, type ActivePreview } from "./hooks/useAppState";
import type { AppService } from "./lib/appService";
import type {
  ApplyMode,
  HistoryDocumentSummary,
  HistoryRevision,
  HistoryRound,
  RoundProgress,
  RunExecutionOptions,
} from "./types/app";

type Props = {
  service: AppService;
  pickerLabel?: string;
};

type PageKey = "workspace" | "history" | "result" | "reduce-text";

const PAGE_META: Array<{ key: PageKey; title: string; description: string }> = [
  { key: "workspace", title: "文档工作台", description: "模型设置、导入文档和整轮续跑" },
  { key: "reduce-text", title: "直接降AIGC", description: "粘贴AI生成文本，直接输出降重结果" },
  { key: "history", title: "历史记录", description: "查看轮次结果、修订版与导出记录" },
  { key: "result", title: "预览", description: "按段落选择后生成修订版或下一轮局部处理" },
];

function formatRuntimeStep(progress: RoundProgress | null, fallback: string): string {
  if (!progress) {
    return fallback;
  }
  if (progress.phase === "chunk-error") {
    return `第 ${progress.round} 轮已暂停，第 ${progress.currentChunk}/${progress.totalChunks} 块处理失败`;
  }
  if (progress.phase === "processing-chunk" && progress.currentChunk && progress.totalChunks) {
    return `正在执行第 ${progress.round} 轮，第 ${progress.currentChunk}/${progress.totalChunks} 块`;
  }
  if (progress.phase === "chunking-ready" && progress.totalChunks) {
    const prefix = progress.resumed ? "已恢复断点" : "已完成切块";
    const completed = progress.completedChunks ? `，已完成 ${progress.completedChunks} 块` : "";
    return `第 ${progress.round} 轮${prefix}，共 ${progress.totalChunks} 块${completed}，准备开始处理`;
  }
  if (progress.phase === "chunk-skipped" && progress.currentChunk && progress.totalChunks) {
    return `第 ${progress.round} 轮跳过已完成块，第 ${progress.currentChunk}/${progress.totalChunks} 块已复用`;
  }
  if (progress.phase === "restoring-output") {
    return `第 ${progress.round} 轮分块处理完成，正在恢复完整输出`;
  }
  if (progress.phase === "chunk-complete" && progress.currentChunk && progress.totalChunks) {
    return `第 ${progress.round} 轮已完成第 ${progress.currentChunk}/${progress.totalChunks} 块`;
  }
  if (progress.phase === "stopped") {
    return progress.message || `第 ${progress.round} 轮已停止，可从当前进度继续`;
  }
  if (progress.phase === "reduce-round-start") {
    return progress.message || `开始第 ${progress.round}/${progress.totalRounds} 轮降 AIGC 处理`;
  }
  return fallback;
}

function describeDocumentProgress(nextRound: number | null, hasNextRound: boolean): string {
  if (hasNextRound && nextRound) {
    return `当前可执行第 ${nextRound} 轮。`;
  }
  return "当前文档已完成全部轮次。";
}

function describeProgressStatus(status: string): string {
  if (status === "completed") {
    return "已完成";
  }
  if (status === "in_progress") {
    return "处理中";
  }
  if (status === "paused") {
    return "已暂停，等待手动继续";
  }
  if (status === "stopped") {
    return "已停止，可从当前进度继续";
  }
  return "未开始";
}

function describePromptProfile(promptProfile: "cn" | "en"): string {
  return promptProfile === "en" ? "英文单轮提示词" : "中文双轮提示词";
}

function buildActivePreviewFromVersion(
  label: string,
  item: HistoryRound | HistoryRevision,
  preview: Awaited<ReturnType<AppService["readOutputPreview"]>>,
): ActivePreview {
  return {
    label,
    round: item.kind === "revision" ? item.sourceRound ?? item.targetRound ?? 0 : item.round,
    revisionNumber: item.kind === "revision" ? item.revisionNumber : item.revisionNumber ?? null,
    outputPath: item.outputPath,
    manifestPath: item.manifestPath,
    kind: item.kind,
    sourceRound: item.kind === "revision" ? item.sourceRound ?? item.targetRound ?? 0 : item.round,
    preview,
  };
}

function buildDisplayNameMap(items: HistoryDocumentSummary[], currentDocId: string | null, currentDisplayName: string | null): Map<string, string> {
  const usageCount = new Map<string, number>();
  const displayMap = new Map<string, string>();
  const orderedItems = items.map((item) => ({
    docId: item.docId,
    rawName: item.displayName || item.originPath || item.sourcePath || item.docId,
  }));

  if (currentDocId && currentDisplayName && !orderedItems.some((item) => item.docId === currentDocId)) {
    orderedItems.unshift({ docId: currentDocId, rawName: currentDisplayName });
  }

  orderedItems.forEach((item) => {
    const nextIndex = usageCount.get(item.rawName) ?? 0;
    usageCount.set(item.rawName, nextIndex + 1);
    displayMap.set(item.docId, nextIndex === 0 ? item.rawName : `${item.rawName}（${nextIndex}）`);
  });

  return displayMap;
}

export function App({ service, pickerLabel }: Props) {
  const progressUnlistenRef = useRef<null | (() => void)>(null);
  const reduceTextUnlistenRef = useRef<null | (() => void)>(null);
  const [stopBusy, setStopBusy] = useState(false);
  const [reduceTextInput, setReduceTextInput] = useState("");
  const [reduceTextOutput, setReduceTextOutput] = useState("");
  const [currentPage, setCurrentPage] = useState<PageKey>("workspace");
  const {
    modelConfig,
    documentStatus,
    history,
    historyItems,
    historyPanelOpen,
    roundResult,
    progress,
    activePreview,
    selectedParagraphIndexes,
    runtimeStep,
    notice,
    busy,
    error,
    setModelConfig,
    setDocumentStatus,
    setHistory,
    setHistoryItems,
    setHistoryPanelOpen,
    setRoundResult,
    setProgress,
    setPreviewText,
    setActivePreview,
    setSelectedParagraphIndexes,
    setRuntimeStep,
    setNotice,
    setBusy,
    setError,
  } = useAppState();
  const displayNameMap = buildDisplayNameMap(historyItems, documentStatus?.docId ?? null, documentStatus?.displayName ?? null);
  const currentDisplayName = documentStatus ? (displayNameMap.get(documentStatus.docId) || documentStatus.displayName || documentStatus.docId) : undefined;

  useEffect(() => {
    service.loadModelConfig()
      .then((config) => setModelConfig(config))
      .catch((appError: unknown) => setError(String(appError)));
  }, [service, setError, setModelConfig]);

  useEffect(() => {
    service.listDocumentHistories()
      .then((result) => setHistoryItems(result.items))
      .catch((appError: unknown) => setError(String(appError)));
  }, [service, setError, setHistoryItems]);

  useEffect(() => {
    return () => {
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
      reduceTextUnlistenRef.current?.();
      reduceTextUnlistenRef.current = null;
    };
  }, []);

  async function refreshDocumentState(sourcePath: string, config = modelConfig) {
    const [status, nextHistory] = await Promise.all([
      service.getDocumentStatus(sourcePath, config),
      service.getDocumentHistory(sourcePath),
    ]);
    setDocumentStatus(status);
    setHistory(nextHistory);
    return status;
  }

  async function refreshHistoryList() {
    const result = await service.listDocumentHistories();
    setHistoryItems(result.items);
    return result.items;
  }

  function clearPreviewSelection() {
    setSelectedParagraphIndexes([]);
  }

  async function handleSelectHistory(item: HistoryDocumentSummary) {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在加载历史文档");
      const status = await refreshDocumentState(item.sourcePath);
      setCurrentPage("workspace");
      setRoundResult(null);
      setPreviewText("");
      setActivePreview(null);
      clearPreviewSelection();
      setNotice(`已切换到历史文档，${describeDocumentProgress(status.nextRound, status.hasNextRound)}`);
      setRuntimeStep(
        status.hasNextRound && status.nextRound
          ? `已加载历史文档，当前可执行第 ${status.nextRound} 轮`
          : "已加载历史文档，全部轮次已完成",
      );
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("加载历史文档失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteHistory(docId: string, fromRound?: number) {
    const actionLabel = fromRound ? `删除第 ${fromRound} 轮及之后的历史` : "删除整条历史";
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(`正在${actionLabel}`);
      const result = await service.deleteDocumentHistory(docId, fromRound);
      const items = await refreshHistoryList();
      if (documentStatus?.docId === docId) {
        if (result.removedDocument) {
          setDocumentStatus(null);
          setHistory(null);
          setRoundResult(null);
          setPreviewText("");
          setActivePreview(null);
          clearPreviewSelection();
        } else {
          const matchedItem = items.find((entry) => entry.docId === docId);
          if (matchedItem) {
            await refreshDocumentState(matchedItem.sourcePath);
            setRoundResult(null);
            setPreviewText("");
            setActivePreview(null);
            clearPreviewSelection();
          }
        }
      }
      const deletedText = result.deletedRounds.length
        ? `已删除轮次：${result.deletedRounds.join(", ")}`
        : "没有匹配到可删除的轮次";
      setNotice(result.removedDocument ? `历史已删除。${deletedText}` : `历史已更新。${deletedText}`);
      setRuntimeStep(result.removedDocument ? "历史删除完成" : "历史回滚完成");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep(`${actionLabel}失败`);
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveModelConfig() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在保存模型设置");
      const saved = await service.saveModelConfig(modelConfig);
      setModelConfig(saved);
      if (documentStatus) {
        await refreshDocumentState(documentStatus.sourcePath, saved);
      }
      setNotice(`模型设置已保存到本地，当前模式为 ${describePromptProfile(saved.promptProfile)}。`);
      setRuntimeStep("模型设置已保存");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("保存模型设置失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleTestConnection() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(modelConfig.offlineMode ? "离线模式无需测试接口" : "正在测试接口连通性");
      const result = await service.testModelConnection(modelConfig);
      setNotice(
        result.message
        + (result.apiType ? ` 类型：${result.apiType}` : "")
        + (result.endpoint ? ` 接口：${result.endpoint}` : ""),
      );
      setRuntimeStep(result.offlineMode ? "离线模式已确认" : "接口连通性测试成功");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("接口连通性测试失败");
    } finally {
      setBusy(false);
    }
  }

  async function handlePickFile() {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在选择并读取文档");
      const picked = await service.pickInputFile();
      if (!picked) {
        setNotice("已取消选择文档。");
        setRuntimeStep("待命");
        return;
      }
      const status = await refreshDocumentState(picked.sourcePath);
      await refreshHistoryList();
      const preview = await service.readSourcePreview(status.currentInputPath, status.manifestPath, modelConfig.promptProfile);
      setCurrentPage("result");
      setHistoryPanelOpen(true);
      setRoundResult(null);
      setPreviewText(preview.text);
      setActivePreview({
        label: "初始预览",
        round: 0,
        revisionNumber: null,
        outputPath: status.currentInputPath,
        manifestPath: status.manifestPath,
        kind: "round",
        sourceRound: 0,
        preview,
      });
      clearPreviewSelection();
      setRuntimeStep(
        status.hasNextRound && status.nextRound
          ? `已载入文档，当前可执行第 ${status.nextRound} 轮`
          : "已载入文档，全部轮次已完成",
      );
      const resumeNotice = status.canResume && status.totalChunkCount && status.completedChunkCount
        ? `检测到第 ${status.nextRound} 轮已有 ${status.completedChunkCount}/${status.totalChunkCount} 块进度，可直接续跑。`
        : "";
      const partialNotice = status.targetParagraphIndexes.length
        ? ` 当前断点仅处理 ${status.targetParagraphIndexes.length} 段。`
        : "";
      const errorNotice = status.lastError ? ` 当前暂停原因：${status.lastError}` : "";
      const stopNotice = status.stopReason ? ` 当前停止说明：${status.stopReason}` : "";
      setNotice(
        `已导入文档，当前使用 ${describePromptProfile(modelConfig.promptProfile)}，${describeDocumentProgress(status.nextRound, status.hasNextRound)}${resumeNotice}${partialNotice}${errorNotice}${stopNotice}`,
      );
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("读取文档失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleStopRound() {
    if (!documentStatus || !busy) {
      return;
    }
    try {
      setStopBusy(true);
      setError("");
      setNotice("已发送停止请求，当前块处理完成后会停下。");
      setRuntimeStep("停止请求已发送，等待当前块收尾");
      const status = await service.requestStop(documentStatus.sourcePath, modelConfig);
      setDocumentStatus(status);
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("发送停止请求失败");
    } finally {
      setStopBusy(false);
    }
  }

  async function executeRound(executionOptions?: RunExecutionOptions | null) {
    if (!documentStatus) {
      setNotice("请先导入一个 txt 或 docx 文档。");
      return;
    }
    if (!documentStatus.hasNextRound && !executionOptions) {
      setNotice("当前文档已完成全部轮次，如需重跑请先从历史记录回滚。");
      return;
    }
    try {
      setBusy(true);
      setStopBusy(false);
      setError("");
      setNotice("");
      setProgress(null);
      progressUnlistenRef.current?.();
      const runToken = await service.startRunRound(documentStatus.sourcePath, modelConfig, executionOptions);
      await refreshHistoryList();
      progressUnlistenRef.current = await service.listenRoundProgress((nextProgress) => {
        setProgress(nextProgress);
        setRuntimeStep(formatRuntimeStep(nextProgress, "处理中"));
        if (nextProgress.phase === "chunk-error") {
          setNotice(nextProgress.error || "本轮已暂停，请检查网络或模型接口后手动继续。");
        }
        if (nextProgress.phase === "stopped") {
          setNotice(nextProgress.message || "已按你的请求停止，当前进度已保留。");
        }
      }, runToken);
      const runLabel = executionOptions?.applyMode === "current_round_revision"
        ? `准备生成第 ${executionOptions.targetRound} 轮修订版`
        : executionOptions?.applyMode === "next_round_partial"
          ? `准备执行第 ${executionOptions.targetRound} 轮局部处理`
          : `准备执行第 ${documentStatus.nextRound} 轮`;
      setRuntimeStep(runLabel);
      const result = await service.awaitRunRound(documentStatus.sourcePath, modelConfig, runToken, executionOptions);
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
      setProgress(null);
      setRoundResult(result);
      setPreviewText(result.paragraphs.map((paragraph) => paragraph.text).join("\n\n"));
      setActivePreview({
        label: result.revisionNumber ? `第 ${result.round} 轮 / 修订 ${result.revisionNumber}` : "当前最新结果",
        round: result.round,
        revisionNumber: result.revisionNumber ?? null,
        outputPath: result.outputPath,
        manifestPath: result.manifestPath,
        kind: "current-result",
        sourceRound: result.sourceRound ?? result.round,
        preview: {
          path: result.outputPath,
          text: result.paragraphs.map((paragraph) => paragraph.text).join("\n\n"),
          paragraphs: result.paragraphs,
        },
      });
      clearPreviewSelection();
      const status = await refreshDocumentState(documentStatus.sourcePath);
      await refreshHistoryList();
      setCurrentPage("result");
      setHistoryPanelOpen(true);
      setRuntimeStep(
        status.hasNextRound && status.nextRound
          ? `第 ${result.round} 轮完成，下一步可执行第 ${status.nextRound} 轮`
          : `第 ${result.round} 轮完成，当前文档全部轮次已结束`,
      );
      if (executionOptions?.applyMode === "current_round_revision") {
        setNotice(`第 ${result.round} 轮修订版已生成，本次处理了 ${result.targetParagraphIndexes.length} 段。`);
      } else if (executionOptions?.applyMode === "next_round_partial") {
        setNotice(`第 ${result.round} 轮局部处理已完成，本次处理了 ${result.targetParagraphIndexes.length} 段。`);
      } else {
        setNotice(
          status.hasNextRound
            ? `第 ${result.round} 轮已完成${result.resumed ? "，本次为断点续跑" : ""}，可以继续导出或进入下一轮。`
            : `第 ${result.round} 轮已完成${result.resumed ? "，本次为断点续跑" : ""}，当前文档的全部轮次已结束，可以直接导出。`,
        );
      }
    } catch (appError) {
      progressUnlistenRef.current?.();
      progressUnlistenRef.current = null;
      const latestStatus = await refreshDocumentState(documentStatus.sourcePath).catch(() => null);
      await refreshHistoryList().catch(() => null);
      const interruptedMessage = latestStatus?.status === "interrupted"
        ? latestStatus.lastError || latestStatus.stopReason || "网络异常或模型请求失败，当前轮已中断，可继续续跑。"
        : "";
      const stoppedMessage = latestStatus?.progressStatus === "stopped"
        ? latestStatus.stopReason || "已按你的请求停止，当前进度已保留。"
        : "";
      setProgress(null);
      setError(interruptedMessage && !stoppedMessage ? interruptedMessage : stoppedMessage ? "" : String(appError));
      setNotice(
        interruptedMessage
          ? `已中断在第 ${latestStatus?.targetRound ?? latestStatus?.nextRound ?? documentStatus.nextRound} 轮，保留已完成进度，可随时继续。`
          : stoppedMessage
            ? `已停止在第 ${latestStatus?.targetRound ?? latestStatus?.nextRound ?? documentStatus.nextRound} 轮，保留已完成进度，可随时继续。`
            : "",
      );
      setRuntimeStep(
        interruptedMessage
          ? "执行已中断，等待手动继续"
          : stoppedMessage
            ? "执行已停止，等待手动继续"
            : "执行轮次失败",
      );
    } finally {
      setStopBusy(false);
      setBusy(false);
    }
  }

  async function handleRunRound() {
    await executeRound(null);
  }

  async function handleReduceText() {
    if (!reduceTextInput.trim()) {
      setNotice("请先粘贴需要降AIGC的文本。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setProgress(null);
      setReduceTextOutput("");
      reduceTextUnlistenRef.current?.();
      const runToken = await service.startReduceText(reduceTextInput, modelConfig);
      reduceTextUnlistenRef.current = await service.listenRoundProgress((nextProgress) => {
        setProgress(nextProgress);
        if (nextProgress.phase === "reduce-round-start") {
          setRuntimeStep(nextProgress.message || `开始第 ${nextProgress.round} 轮降 AIGC 处理`);
        } else {
          setRuntimeStep(formatRuntimeStep(nextProgress, "降AIGC处理中"));
        }
        if (nextProgress.phase === "chunk-error") {
          setNotice(nextProgress.error || "本轮已暂停，请检查网络或模型接口。");
        }
        if (nextProgress.phase === "stopped") {
          setNotice(nextProgress.message || "已停止，当前进度已保留。");
        }
      }, runToken);
      setRuntimeStep("正在降AIGC，等待结果...");
      const result = await service.awaitReduceText(runToken);
      reduceTextUnlistenRef.current?.();
      reduceTextUnlistenRef.current = null;
      setProgress(null);
      setReduceTextOutput(result.reduceText);
      setRuntimeStep("降AIGC处理完成");
      setNotice("文本降AIGC处理完成，可复制结果。");
    } catch (appError) {
      reduceTextUnlistenRef.current?.();
      reduceTextUnlistenRef.current = null;
      setProgress(null);
      setError(String(appError));
      setRuntimeStep("降AIGC处理失败");
    } finally {
      setBusy(false);
    }
  }

  function handleCopyReduceText() {
    if (!reduceTextOutput) return;
    navigator.clipboard.writeText(reduceTextOutput)
      .then(() => setNotice("结果已复制到剪贴板。"))
      .catch(() => setNotice("复制失败，请手动复制。"));
  }

  async function handleHistoryDownload(item: HistoryRound | HistoryRevision, targetFormat: "txt" | "docx") {
    if (!item.outputPath) {
      setNotice("当前历史记录没有可导出的输出路径。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      const label = item.kind === "revision"
        ? `第 ${item.sourceRound ?? item.targetRound} 轮修订 ${item.revisionNumber}`
        : `第 ${item.round} 轮`;
      setRuntimeStep(`正在导出 ${label} ${targetFormat.toUpperCase()}`);
      const result = await service.exportRound(item.outputPath, targetFormat);
      setNotice(`${label} 已导出 ${result.format.toUpperCase()}：${result.path}`);
      setRuntimeStep(`${label} 导出完成`);
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("导出失败");
    } finally {
      setBusy(false);
    }
  }

  async function handlePreviewHistoryVersion(item: HistoryRound | HistoryRevision) {
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep("正在读取历史预览");
      const preview = await service.readOutputPreview(item.outputPath, item.manifestPath);
      const label = item.kind === "revision"
        ? `历史预览：第 ${item.sourceRound ?? item.targetRound} 轮 / 修订 ${item.revisionNumber}`
        : `历史预览：第 ${item.round} 轮`;
      setActivePreview(buildActivePreviewFromVersion(label, item, preview));
      setPreviewText(preview.text);
      clearPreviewSelection();
      setCurrentPage("result");
      setNotice("已打开历史版本预览，可以按段落选择并继续处理。");
      setRuntimeStep("历史预览已加载");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("读取历史预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(targetFormat: "txt" | "docx") {
    const exportPath = activePreview?.outputPath ?? roundResult?.outputPath;
    if (!exportPath) {
      setNotice("请先打开一个可导出的结果预览。");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setNotice("");
      setRuntimeStep(`正在导出 ${targetFormat.toUpperCase()}`);
      const result = await service.exportRound(exportPath, targetFormat);
      setNotice(`已导出 ${result.format.toUpperCase()}：${result.path}`);
      setRuntimeStep("导出完成");
    } catch (appError) {
      setError(String(appError));
      setRuntimeStep("导出失败");
    } finally {
      setBusy(false);
    }
  }

  function toggleParagraph(paragraphIndex: number) {
    setSelectedParagraphIndexes(
      selectedParagraphIndexes.includes(paragraphIndex)
        ? selectedParagraphIndexes.filter((value) => value !== paragraphIndex)
        : [...selectedParagraphIndexes, paragraphIndex].sort((left, right) => left - right),
    );
  }

  function buildExecutionOptions(applyMode: ApplyMode): RunExecutionOptions | null {
    if (!activePreview || !selectedParagraphIndexes.length) {
      setNotice("请先选择至少一个段落。");
      return null;
    }
    const sourceRound = activePreview.round;
    const targetRound = applyMode === "current_round_revision" ? sourceRound : sourceRound + 1;
    return {
      applyMode,
      targetParagraphIndexes: selectedParagraphIndexes,
      sourceRound,
      targetRound,
      basedOnOutputPath: activePreview.outputPath,
      basedOnManifestPath: activePreview.manifestPath,
      revisionNumber: activePreview.revisionNumber,
    };
  }

  async function handleCreateRevision() {
    if (activePreview?.kind === "round" && activePreview.round === 0) {
      setNotice("初始预览还没有当前轮结果，请使用“在下一轮处理所选段落”。");
      return;
    }
    const options = buildExecutionOptions("current_round_revision");
    if (!options) {
      return;
    }
    await executeRound(options);
  }

  async function handleRunNextPartial() {
    const options = buildExecutionOptions("next_round_partial");
    if (!options) {
      return;
    }
    await executeRound(options);
  }

  const activePage = PAGE_META.find((item) => item.key === currentPage) ?? PAGE_META[0];

  return (
    <main className="app-shell">
      <div className="hero-panel">
        <div className="hero-copy-wrap">
          <p className="eyebrow">baibaiAIGC</p>
          <h1>段落级 AIGC 文稿处理工作台</h1>
        </div>
        <div className="hero-status-column">
          <span className={`status-tag ${busy ? "" : "idle"}`}>
            {busy ? (progress?.round ? `第 ${progress.round} 轮运行中` : "处理中") : "待命"}
          </span>
          <div className="hero-status-note">
            <span>当前页面</span>
            <strong>{activePage.title}</strong>
          </div>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="notice-banner">{notice}</div> : null}

      <div className="runtime-log" aria-live="polite">
        <span className="runtime-log-label">运行步骤</span>
        <strong>{formatRuntimeStep(progress, runtimeStep)}</strong>
      </div>

      <nav className="page-switcher" aria-label="页面切换">
        {PAGE_META.map((page) => (
          <button
            key={page.key}
            type="button"
            className={`page-tab ${page.key === currentPage ? "active" : ""}`}
            onClick={() => setCurrentPage(page.key)}
          >
            <strong>{page.title}</strong>
            <span>{page.description}</span>
          </button>
        ))}
      </nav>

      <section className={`page-frame ${currentPage === "workspace" ? "" : "page-frame-compact"}`}>
        {currentPage === "workspace" ? (
          <div className="page-frame-head">
            <div>
              <p className="page-kicker">页面内容</p>
              <h2>{activePage.title}</h2>
            </div>
            <p>{activePage.description}</p>
          </div>
        ) : null}

        {currentPage === "workspace" ? (
          <div className="content-grid">
            <ModelConfigCard
              value={modelConfig}
              busy={busy}
              onChange={setModelConfig}
              onSave={handleSaveModelConfig}
              onTestConnection={handleTestConnection}
            />
            <DocumentCard
              value={documentStatus}
              displayName={currentDisplayName}
              busy={busy}
              stopBusy={stopBusy}
              onPickFile={handlePickFile}
              onRunRound={handleRunRound}
              onStop={handleStopRound}
              pickerLabel={pickerLabel}
              progressStatusLabel={documentStatus ? describeProgressStatus(documentStatus.progressStatus) : "未开始"}
            />
          </div>
        ) : null}

        {currentPage === "reduce-text" ? (
          <TextReduceCard
            inputText={reduceTextInput}
            outputText={reduceTextOutput}
            busy={busy}
            onInputChange={setReduceTextInput}
            onReduce={handleReduceText}
            onCopy={handleCopyReduceText}
          />
        ) : null}

        {currentPage === "history" ? (
          <HistoryCard
            currentDocId={documentStatus?.docId ?? null}
            currentHistory={history}
            items={historyItems}
            open={historyPanelOpen}
            busy={busy}
            embedded
            onToggle={() => setHistoryPanelOpen(!historyPanelOpen)}
            onSelect={handleSelectHistory}
            onDelete={handleDeleteHistory}
            onDownload={handleHistoryDownload}
            onPreview={handlePreviewHistoryVersion}
          />
        ) : null}

        {currentPage === "result" ? (
          <ResultCard
            result={roundResult}
            activePreview={activePreview}
            selectedParagraphIndexes={selectedParagraphIndexes}
            busy={busy}
            onToggleParagraph={toggleParagraph}
            onSelectAllParagraphs={() => {
              setSelectedParagraphIndexes(activePreview?.preview.paragraphs.map((paragraph) => paragraph.paragraphIndex) ?? []);
            }}
            onClearParagraphs={clearPreviewSelection}
            onCreateRevision={handleCreateRevision}
            onRunNextPartial={handleRunNextPartial}
            onExportTxt={() => handleExport("txt")}
            onExportDocx={() => handleExport("docx")}
          />
        ) : null}
      </section>
    </main>
  );
}
