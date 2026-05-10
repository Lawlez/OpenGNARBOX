import React, { useState, useRef, useEffect } from 'react';
import { 
  FolderIcon, 
  CogIcon, 
  ArrowPathIcon,
  ShieldCheckIcon,
  BoltIcon,
  FolderOpenIcon,
  ComputerDesktopIcon,
  DocumentCheckIcon,
  XCircleIcon,
  ExclamationTriangleIcon,
  StopCircleIcon,
  CubeTransparentIcon,
  EyeSlashIcon,
  ArrowPathRoundedSquareIcon,
  SignalIcon
} from '@heroicons/react/24/outline';
import { 
  FileNode, 
  AppConfig, 
  Job, 
  TransactionStatus,
  DuplicateStrategy,
  FinalReport
} from './types';
import { fileService } from './services/FileService';
import { calculateDestinationPath } from './services/organizer';
import FileSystemTree from './components/FileSystemTree';
import TransactionMonitor from './components/TransactionMonitor';
import FileBrowser from './components/FileBrowser';

const DEFAULT_CONFIG: AppConfig = {
  backupRetentionDays: 7,
  organizationPattern: '{Camera}_{Year}/{Month}/{Ext}/{YYYY-MM-DD}_{Camera}_{File}',
  enableBackup: true,
  duplicateStrategy: DuplicateStrategy.SKIP,
  ignoredExtensions: ['.xml', '.thm', '.lrv', '.dat'] // Default ignored files
};

export default function App() {
  const [activeTab, setActiveTab] = useState<'organize' | 'settings' | 'browse'>('organize');
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const folders = {
    source: '/media/mmc_mmcblk2p1',
    library: '/media/GNARBOX/library',
    backup: '/media/GNARBOX/backup'
  };

  const [incomingFiles, setIncomingFiles] = useState<FileNode[]>([]);
  const [libraryFiles, setLibraryFiles] = useState<FileNode[]>([]);
  
  // Transaction State
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  
  // Control
  const abortController = useRef<boolean>(false);
  
  // Move vs Copy
  const [isMoveMode, setIsMoveMode] = useState(true);

  // Manual Duplicate Resolution State
  const [manualConflict, setManualConflict] = useState<{
    jobId: string;
    incomingFile: FileNode;
    existingFile: FileNode | null; 
    destPath: string;
    resolve: (strategy: DuplicateStrategy) => void;
  } | null>(null);

  // Final Report State
  const [finalReport, setFinalReport] = useState<FinalReport | null>(null);

  // Power / System State
  const [powerState, setPowerState] = useState<{
    level: number | null;
    status: string;
    ac_online: boolean;
  }>({ level: null, status: 'unknown', ac_online: false });
  const [rebootConfirm, setRebootConfirm] = useState(false);

  // Poll power status
  useEffect(() => {
    const fetchPower = async () => {
      try {
        const res = await fetch('/api/system/power');
        if (res.ok) {
          const data = await res.json();
          setPowerState(data);
        }
      } catch { /* ignore */ }
    };
    fetchPower();
    const interval = setInterval(fetchPower, 30000);
    return () => clearInterval(interval);
  }, []);

  // Helper to filter ignored extensions
  const filterFiles = (files: FileNode[]) => {
    return files.filter(f => {
      // Extension includes dot? standardize:
      const ext = f.extension.startsWith('.') ? f.extension.toLowerCase() : '.' + f.extension.toLowerCase();
      // Check config
      const isIgnored = config.ignoredExtensions.some(ignored => ignored.toLowerCase() === ext);
      return !isIgnored;
    });
  };

  // Re-scan handlers
  const rescanAll = async () => {
    try {
      const sFiles = await fileService.scanDirectory(folders.source);
      setIncomingFiles(filterFiles(sFiles));
      const lFiles = await fileService.scanDirectory(folders.library);
      setLibraryFiles(filterFiles(lFiles));
    } catch (e) {
      console.error(e);
    }
  };

  // Auto-fetch on mount and config change
  useEffect(() => {
    rescanAll();
  }, [config.ignoredExtensions]);

  const handleManualResolution = (strategy: DuplicateStrategy) => {
    if (manualConflict) {
      manualConflict.resolve(strategy);
      setManualConflict(null);
    }
  };

  const stopProcessing = () => {
    abortController.current = true;
  };

  const runOrganization = async () => {
    if (!folders.source || !folders.library || (config.enableBackup && !folders.backup)) {
      alert("Please connect required folders.");
      return;
    }

    setIsProcessing(true);
    abortController.current = false;
    setJobs([]);
    setFinalReport(null);
    
    const startTime = Date.now();
    let processedCount = 0;
    let skippedCount = 0;
    let errorCount = 0;
    let duplicateCount = 0;
    let totalSizeMB = 0;
    
    // Cache for Source files in this batch to prevent processing same file twice
    const batchHashes = new Set<string>();
    
    // Cache for Library Hashes to avoid re-hashing library files repeatedly
    const libraryHashCache = new Map<string, string>(); // Path -> Hash

    // Populate cache with known hashes from state
    libraryFiles.forEach(f => {
      if (f.hash) libraryHashCache.set(f.currentPath, f.hash);
    });

    const newJobs: Job[] = incomingFiles.map(file => ({
      id: `job-${file.id}`,
      fileId: file.id,
      sourcePath: file.currentPath,
      proposedPath: calculateDestinationPath(file, { ...config, backupLocation: folders.backup, libraryRoot: folders.library }),
      status: TransactionStatus.PENDING,
      timestamp: Date.now()
    }));

    setJobs(newJobs);

    for (let i = 0; i < newJobs.length; i++) {
      if (abortController.current) {
        updateJobStatus(newJobs[i].id, TransactionStatus.STOPPED);
        continue;
      }

      const job = newJobs[i];
      const fileNode = incomingFiles.find(f => f.id === job.fileId);
      
      if (!fileNode) {
        updateJobStatus(job.id, TransactionStatus.FAILED, "File node lost");
        errorCount++;
        continue;
      }

      try {
        // --- Step 1: Read & Hash Source ---
        updateJobStatus(job.id, TransactionStatus.HASHING_SOURCE);
        const sourceHash = await fileService.hashFile(fileNode.currentPath);
        
        let destPath = job.proposedPath;
        let shouldProcess = true;

        // --- Step 2: Deep Deduplication Check ---
        // 2a. Check against other files in this batch
        if (batchHashes.has(sourceHash)) {
            duplicateCount++;
            updateJobStatus(job.id, TransactionStatus.SKIPPED, "Duplicate in batch");
            skippedCount++;
            shouldProcess = false;
        } else {
             batchHashes.add(sourceHash);

             // 2b. Check against Library
             // First filter by size (fastest rejection)
             const potentialDupes = libraryFiles.filter(lf => lf.size === fileNode.size);
             let foundLibraryDupe: FileNode | null = null;
             
             for (const candidate of potentialDupes) {
                 // Check Cache first
                 let candidateHash = libraryHashCache.get(candidate.currentPath);
                 
                 if (!candidateHash) {
                     // Compute if missing
                     candidateHash = await fileService.hashFile(candidate.currentPath);
                     libraryHashCache.set(candidate.currentPath, candidateHash);
                 }

                 if (candidateHash === sourceHash) {
                     foundLibraryDupe = candidate;
                     break;
                 }
             }

             let conflictFile = foundLibraryDupe;
             
             // 2c. Check for Filename Collision at Destination (if not content duplicate)
             if (!conflictFile) {
                 // Check if a file already exists at the proposed path
                 // (Note: libraryFiles contains the scan of the library)
                 const fileAtDest = libraryFiles.find(lf => lf.currentPath === destPath);
                 if (fileAtDest) {
                    conflictFile = fileAtDest; 
                 }
             }

             if (conflictFile) {
                duplicateCount++;
                let strategy = config.duplicateStrategy;
                
                // If it's a content match (true duplicate), we might treat it differently than just a filename collision
                const isContentMatch = foundLibraryDupe !== null;

                if (strategy === DuplicateStrategy.ASK) {
                    updateJobStatus(job.id, TransactionStatus.WAITING_FOR_USER);
                    strategy = await new Promise<DuplicateStrategy>((resolve) => {
                        setManualConflict({
                            jobId: job.id,
                            incomingFile: fileNode,
                            existingFile: conflictFile,
                            destPath: destPath,
                            resolve
                        });
                    });
                }

                if (strategy === DuplicateStrategy.SKIP) {
                    updateJobStatus(job.id, TransactionStatus.SKIPPED, isContentMatch ? "Already in library" : "Filename exists");
                    skippedCount++;
                    shouldProcess = false;
                } else if (strategy === DuplicateStrategy.OVERWRITE) {
                    // We don't delete here, the copy will overwrite or we delete explicitly
                    try { await fileService.deleteFile(destPath); } catch {} 
                } else if (strategy === DuplicateStrategy.RENAME) {
                     const ext = destPath.split('.').pop();
                     const base = destPath.replace(`.${ext}`, '');
                     // Basic renaming strategy: append timestamp
                     destPath = `${base}_${Date.now().toString().slice(-6)}.${ext}`;
                }
             }
        }

        if (shouldProcess) {
            // --- Step 3: Backup ---
            if (config.enableBackup && folders.backup) {
                updateJobStatus(job.id, TransactionStatus.BACKING_UP);
                const backupFolder = `${folders.backup}/backup_${new Date().toISOString().split('T')[0]}`;
                const backupPath = `${backupFolder}/${fileNode.name}`;
                await fileService.copyFile(fileNode.currentPath, backupPath, (p) => {
                   setJobs(prev => prev.map(j => j.id === job.id ? { ...j, progress: p } : j));
                });
            }

            // --- Step 4: Write to Library ---
            updateJobStatus(job.id, TransactionStatus.MOVING);
            await fileService.copyFile(fileNode.currentPath, destPath, (p) => {
                setJobs(prev => prev.map(j => j.id === job.id ? { ...j, progress: p } : j));
            });

            // --- Step 5: Verify ---
            updateJobStatus(job.id, TransactionStatus.VERIFYING);
            const destHash = await fileService.hashFile(destPath);

            // Verify integrity
            if (destHash === sourceHash) {
                if (isMoveMode) {
                    await fileService.deleteFile(fileNode.currentPath);
                    setIncomingFiles(prev => prev.filter(f => f.id !== fileNode.id));
                }
                updateJobStatus(job.id, TransactionStatus.COMPLETED);
                
                // Add to local library view so it's included in next checks within this session if needed
                // (Though usually we organize batch by batch)
                const newLibraryFile = { ...fileNode, currentPath: destPath, hash: sourceHash };
                setLibraryFiles(prev => [...prev, newLibraryFile]);
                libraryHashCache.set(destPath, sourceHash); // Update cache
                
                processedCount++;
                totalSizeMB += fileNode.size / (1024 * 1024);

            } else {
                updateJobStatus(job.id, TransactionStatus.ROLLED_BACK, "Hash mismatch");
                errorCount++;
                // Try to clean up bad file
                try { await fileService.deleteFile(destPath); } catch {}
            }
        }

      } catch (err: any) {
        console.error(err);
        updateJobStatus(job.id, TransactionStatus.FAILED, err.message || "Unknown error");
        errorCount++;
      }
      
      setProgress(((i + 1) / newJobs.length) * 100);
    }

    setFinalReport({
        totalFiles: newJobs.length,
        totalSizeMB: parseFloat(totalSizeMB.toFixed(2)),
        durationSeconds: (Date.now() - startTime) / 1000,
        processedCount,
        skippedCount,
        errorCount,
        duplicateCount,
        folderSource: folders.source || '',
        folderDest: folders.library || ''
    });
    
    setIsProcessing(false);
  };

  const updateJobStatus = (jobId: string, status: TransactionStatus, error?: string) => {
    setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status, error } : j));
  };

  const stats = {
    totalIncoming: incomingFiles.length,
    images: incomingFiles.filter(f => f.type === 'IMAGE').length,
    videos: incomingFiles.filter(f => f.type === 'VIDEO').length,
    size: (incomingFiles.reduce((acc, f) => acc + f.size, 0) / (1024*1024)).toFixed(2)
  };

  return (
    <div className="flex flex-col md:flex-row h-screen bg-gray-950 text-slate-200 font-sans selection:bg-blue-500 selection:text-white">
      {/* Sidebar — hidden on mobile, shown on md+ */}
      <div className="hidden md:flex w-64 bg-gray-900 border-r border-gray-800 flex-col flex-shrink-0">
        <div className="p-6 flex items-center space-x-3 pt-10">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(37,99,235,0.5)]">
            <CubeTransparentIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <span className="text-xl font-bold tracking-tight text-white block">OpenGNARBOX</span>
            <span className="text-[10px] text-gray-500 font-mono">
              HARDWARE
            </span>
          </div>
        </div>

        <nav className="flex-1 px-4 space-y-2 mt-8 no-drag">
          <SidebarItem 
            icon={<FolderIcon className="w-5 h-5" />} 
            label="Organizer" 
            active={activeTab === 'organize'}
            onClick={() => setActiveTab('organize')}
          />
          <SidebarItem 
            icon={<FolderOpenIcon className="w-5 h-5" />} 
            label="File Browser" 
            active={activeTab === 'browse'}
            onClick={() => setActiveTab('browse')}
          />
          <SidebarItem 
            icon={<CogIcon className="w-5 h-5" />} 
            label="Settings" 
            active={activeTab === 'settings'}
            onClick={() => setActiveTab('settings')}
          />
        </nav>

        {/* Connection Status Panel */}
        <div className="p-4 border-t border-gray-800 space-y-3 no-drag">
           <div className="text-xs font-mono text-gray-500 mb-2 uppercase tracking-wider flex justify-between">
              Connections
              <button title="Rescan Folders" onClick={rescanAll} className="hover:text-white">
                 <ArrowPathIcon className="w-4 h-4" />
              </button>
           </div>
           
           <div className="flex items-center justify-between group">
             <div className="flex items-center gap-2 text-sm text-gray-400">
               <div className={`w-2 h-2 rounded-full ${folders.source ? 'bg-green-500 shadow-[0_0_5px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`}></div>
                Source (SD)
             </div>
           </div>

           <div className="flex items-center justify-between group">
             <div className="flex items-center gap-2 text-sm text-gray-400">
               <div className={`w-2 h-2 rounded-full ${folders.library ? 'bg-green-500 shadow-[0_0_5px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`}></div>
                Library (NVMe)
             </div>
           </div>

           <div className="flex items-center justify-between group">
             <div className="flex items-center gap-2 text-sm text-gray-400">
               <div className={`w-2 h-2 rounded-full ${folders.backup ? 'bg-green-500 shadow-[0_0_5px_rgba(34,197,94,0.5)]' : 'bg-gray-600'}`}></div>
                Backup (NVMe)
             </div>
           </div>
        </div>

         {/* Power / System Panel */}
         <div className="p-4 border-t border-gray-800 space-y-3 no-drag">
            <div className="text-xs font-mono text-gray-500 mb-2 uppercase tracking-wider flex justify-between">
               System
               <SignalIcon className="w-4 h-4 text-green-500" />
            </div>

            {/* AC / Battery Status */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                {powerState.ac_online ? (
                  <BoltIcon className="w-4 h-4 text-yellow-400" />
                ) : (
                  <div className="w-4 h-4 flex items-center justify-center">
                    <svg viewBox="0 0 24 24" className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="2" y="7" width="18" height="10" rx="1" />
                      <rect x="20" y="10" width="2" height="4" rx="0.5" />
                      {powerState.level != null && (
                        <rect x="3" y="8" width={Math.max(1, (powerState.level / 100) * 16)} height="8" rx="0.5" fill="currentColor" className={powerState.level > 20 ? 'text-green-500' : 'text-red-500'} />
                      )}
                    </svg>
                  </div>
                )}
                <span>
                  {powerState.level != null ? `${powerState.level}%` : ''}
                  {powerState.level != null && ' · '}
                  {powerState.ac_online ? 'AC Connected' : powerState.status}
                </span>
              </div>
            </div>

            {/* Reboot */}
            {!rebootConfirm ? (
              <button
                onClick={() => setRebootConfirm(true)}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-red-400 hover:bg-red-950/30 rounded border border-gray-800 hover:border-red-800 transition-all"
              >
                <ArrowPathRoundedSquareIcon className="w-4 h-4" />
                Reboot Device
              </button>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-red-400 text-center">Are you sure?</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setRebootConfirm(false)}
                    className="flex-1 px-3 py-2 text-xs text-gray-400 bg-gray-800 rounded hover:bg-gray-700"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        await fetch('/api/system/reboot', { method: 'POST' });
                      } catch { /* device will go down */ }
                      setRebootConfirm(false);
                    }}
                    className="flex-1 px-3 py-2 text-xs text-white bg-red-600 rounded hover:bg-red-500 font-medium"
                  >
                    Confirm
                  </button>
                </div>
              </div>
            )}
         </div>
      </div>

      {/* Mobile Bottom Tab Bar */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-gray-900 border-t border-gray-800 flex justify-around items-center px-2 py-2 safe-area-pb">
        <button onClick={() => setActiveTab('organize')} className={`flex flex-col items-center gap-1 px-4 py-1 rounded-lg text-xs ${activeTab === 'organize' ? 'text-blue-400' : 'text-gray-500'}`}>
          <FolderIcon className="w-5 h-5" />
          Organizer
        </button>
        <button onClick={() => setActiveTab('browse')} className={`flex flex-col items-center gap-1 px-4 py-1 rounded-lg text-xs ${activeTab === 'browse' ? 'text-blue-400' : 'text-gray-500'}`}>
          <FolderOpenIcon className="w-5 h-5" />
          Browse
        </button>
        <button onClick={() => setActiveTab('settings')} className={`flex flex-col items-center gap-1 px-4 py-1 rounded-lg text-xs ${activeTab === 'settings' ? 'text-blue-400' : 'text-gray-500'}`}>
          <CogIcon className="w-5 h-5" />
          Settings
        </button>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 relative pb-16 md:pb-0">
        
        {/* Manual Conflict Resolution Modal */}
        {manualConflict && (
           <div className="absolute inset-0 z-50 bg-black/80 flex items-center justify-center p-4 md:p-8 backdrop-blur-sm">
             <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-4 md:p-6 max-w-4xl w-full max-h-[90vh] overflow-y-auto">
               <div className="flex items-center gap-3 text-orange-400 mb-6">
                 <ExclamationTriangleIcon className="w-8 h-8" />
                 <h3 className="text-xl font-bold text-white">Duplicate Detected</h3>
               </div>
               <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-8 mb-6 md:mb-8">
                 {/* Incoming */}
                 <div className="bg-gray-950 p-4 rounded border border-gray-800">
                    <h4 className="text-blue-400 text-sm font-bold uppercase mb-4">Incoming File</h4>
                    <div className="space-y-3 text-sm">
                        <div className="flex justify-between border-b border-gray-800 pb-1">
                            <span className="text-gray-500">Name</span>
                            <span className="text-white font-mono">{manualConflict.incomingFile.name}</span>
                        </div>
                        <div className="flex justify-between border-b border-gray-800 pb-1">
                            <span className="text-gray-500">Size</span>
                            <span className="text-white font-mono">{(manualConflict.incomingFile.size / 1024).toFixed(1)} KB</span>
                        </div>
                        <div className="flex justify-between border-b border-gray-800 pb-1">
                            <span className="text-gray-500">Date</span>
                            <span className="text-white font-mono">{manualConflict.incomingFile.createdDate.toLocaleDateString()}</span>
                        </div>
                    </div>
                 </div>
                 {/* Existing */}
                 <div className="bg-gray-950 p-4 rounded border border-gray-800">
                    <h4 className="text-orange-400 text-sm font-bold uppercase mb-4">Existing Library File</h4>
                     {manualConflict.existingFile ? (
                        <div className="space-y-3 text-sm">
                            <div className="flex justify-between border-b border-gray-800 pb-1">
                                <span className="text-gray-500">Name</span>
                                <span className="text-white font-mono">{manualConflict.existingFile.name}</span>
                            </div>
                            <div className="flex justify-between border-b border-gray-800 pb-1">
                                <span className="text-gray-500">Size</span>
                                <span className="text-white font-mono">{(manualConflict.existingFile.size / 1024).toFixed(1)} KB</span>
                            </div>
                            <div className="flex justify-between border-b border-gray-800 pb-1">
                                <span className="text-gray-500">Date</span>
                                <span className="text-white font-mono">{manualConflict.existingFile.createdDate.toLocaleDateString()}</span>
                            </div>
                            <div className="flex justify-between border-b border-gray-800 pb-1">
                                <span className="text-gray-500">Path</span>
                                <span className="text-white font-mono truncate max-w-[200px]" title={manualConflict.existingFile.currentPath}>{manualConflict.existingFile.currentPath}</span>
                            </div>
                        </div>
                     ) : (
                         <div className="text-gray-500 italic">File already exists at destination path (Name Collision)</div>
                     )}
                 </div>
               </div>
               <div className="grid grid-cols-2 gap-3">
                 <button onClick={() => handleManualResolution(DuplicateStrategy.SKIP)} className="p-3 bg-gray-800 hover:bg-gray-700 rounded text-white font-medium border border-gray-700">Skip Incoming</button>
                 <button onClick={() => handleManualResolution(DuplicateStrategy.OVERWRITE)} className="p-3 bg-red-900/50 hover:bg-red-900 rounded text-red-200 font-medium border border-red-800">Overwrite Existing</button>
                 <button onClick={() => handleManualResolution(DuplicateStrategy.RENAME)} className="col-span-2 p-3 bg-blue-600 hover:bg-blue-500 rounded text-white font-medium shadow-lg">Keep Both (Rename Incoming)</button>
               </div>
             </div>
           </div>
        )}

        {/* Final Report Modal */}
        {finalReport && (
           <div className="absolute inset-0 z-50 bg-black/80 flex items-center justify-center p-4 md:p-8 backdrop-blur-sm">
              <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl p-5 md:p-8 max-w-2xl w-full max-h-[90vh] overflow-y-auto">
               <div className="flex justify-between items-start mb-6">
                 <div>
                    <h3 className="text-2xl font-bold text-white flex items-center gap-2">
                      <DocumentCheckIcon className="w-8 h-8 text-green-500" />
                      Organization Complete
                    </h3>
                    <p className="text-gray-400 mt-1">Processed {finalReport.processedCount} files in {finalReport.durationSeconds.toFixed(1)}s</p>
                 </div>
                 <button onClick={() => setFinalReport(null)} className="text-gray-500 hover:text-white">
                   <XCircleIcon className="w-8 h-8" />
                 </button>
               </div>
               {/* Stats Grid */}
               <div className="grid grid-cols-2 gap-3 md:gap-6 mb-6 md:mb-8">
                  <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                    <div className="text-gray-500 text-sm mb-1">Total Data Written</div>
                    <div className="text-2xl font-mono text-blue-400">{finalReport.totalSizeMB} MB</div>
                  </div>
                  <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                    <div className="text-gray-500 text-sm mb-1">Duplicates Skipped</div>
                    <div className="text-2xl font-mono text-orange-400">{finalReport.duplicateCount}</div>
                  </div>
                  <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                    <div className="text-gray-500 text-sm mb-1">Errors</div>
                    <div className="text-2xl font-mono text-red-400">{finalReport.errorCount}</div>
                  </div>
                   <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                    <div className="text-gray-500 text-sm mb-1">Total Files Scanned</div>
                    <div className="text-2xl font-mono text-gray-400">{finalReport.totalFiles}</div>
                  </div>
               </div>
               <button onClick={() => setFinalReport(null)} className="w-full py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium">
                 Close Report
               </button>
             </div>
          </div>
        )}

        {activeTab === 'organize' && (
          <>
            {/* Header */}
            <header className="h-auto min-h-[4rem] border-b border-gray-800 bg-gray-900/50 flex flex-col md:flex-row items-start md:items-center justify-between px-4 md:px-8 py-3 md:py-0 backdrop-blur-md sticky top-0 z-10 gap-3 md:gap-0">
               <div className="no-drag">
                 <h1 className="text-lg font-semibold text-white flex items-center gap-2">
                   <ArrowPathIcon className="w-5 h-5 text-gray-400" />
                   Ingest & Organize
                 </h1>
                 <p className="text-xs text-gray-400 truncate max-w-md" title={folders.source || ''}>
                   {folders.source ? `Connected: ${folders.source}` : 'No Source Connected'}
                 </p>
               </div>
               
               <div className="flex items-center flex-wrap gap-3 md:gap-6 no-drag w-full md:w-auto">
                  {/* Copy/Move Toggle */}
                  <div className="flex items-center bg-gray-800 rounded-lg p-1 border border-gray-700">
                    <button 
                      onClick={() => setIsMoveMode(false)}
                      className={`px-3 py-1 text-xs font-medium rounded transition-all ${!isMoveMode ? 'bg-gray-700 text-white shadow' : 'text-gray-400 hover:text-gray-200'}`}
                    >
                      Copy Only
                    </button>
                    <button 
                      onClick={() => setIsMoveMode(true)}
                      className={`px-3 py-1 text-xs font-medium rounded transition-all ${isMoveMode ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'}`}
                    >
                      Move & Delete
                    </button>
                  </div>

                  <div className="hidden sm:block text-right border-l border-gray-800 pl-4 md:pl-6">
                    <div className="text-sm font-medium text-white">{stats.totalIncoming} Files</div>
                    <div className="text-xs text-gray-400">{stats.size} MB • {stats.images} Img • {stats.videos} Vid</div>
                  </div>
                  
                  {isProcessing ? (
                    <button 
                        onClick={stopProcessing}
                        className="flex items-center gap-2 px-4 py-2 rounded-md font-medium text-sm transition-all bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-500/20"
                    >
                        <StopCircleIcon className="w-4 h-4" />
                        Stop
                    </button>
                  ) : (
                    <button 
                        onClick={runOrganization}
                        disabled={!folders.source || !folders.library || incomingFiles.length === 0}
                        className={`flex items-center gap-2 px-4 py-2 rounded-md font-medium text-sm transition-all ${
                        !folders.source
                            ? 'bg-gray-800 text-gray-500 cursor-not-allowed' 
                            : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-500/20'
                        }`}
                    >
                        <BoltIcon className="w-4 h-4" />
                        Start
                    </button>
                  )}
               </div>
            </header>

            {/* Workspace */}
            <main className="flex-1 flex flex-col md:flex-row overflow-hidden">
              {/* Left Panel: Source */}
              <div className="w-full md:w-1/3 border-b md:border-b-0 md:border-r border-gray-800 bg-gray-900/30 flex flex-col min-h-[200px] md:min-h-0">
                <div className="p-3 bg-gray-900 border-b border-gray-800 text-xs font-semibold text-gray-400 tracking-wider flex justify-between items-center">
                  <span>SOURCE PREVIEW</span>
                </div>
                <div className="flex-1 p-2 overflow-hidden relative">
                  {!folders.source ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-600 gap-4">
                      <FolderOpenIcon className="w-12 h-12 opacity-50" />
                      <p className="text-sm text-center px-6">SD card not detected at /media/mmc_mmcblk2p1</p>
                      <button onClick={rescanAll} className="px-4 py-2 bg-gray-800 rounded text-sm hover:bg-gray-700">Refresh</button>
                    </div>
                  ) : (
                    <FileSystemTree files={incomingFiles} rootName={folders.source.split(/[\\/]/).pop() || 'Source'} />
                  )}
                </div>
              </div>

              {/* Middle Panel: Action Log / Visualizer */}
              <div className="w-full md:w-1/3 border-b md:border-b-0 md:border-r border-gray-800 bg-gray-950 flex flex-col min-h-[200px] md:min-h-0">
                 <div className="p-3 bg-gray-900 border-b border-gray-800 text-xs font-semibold text-gray-400 tracking-wider flex justify-between">
                  <span>TRANSACTION SAFETY LOG</span>
                  {isProcessing && <span className="text-blue-400">{progress.toFixed(0)}%</span>}
                </div>
                <div className="flex-1 p-2 overflow-hidden relative">
                   {jobs.length === 0 && !isProcessing && (
                     <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-700">
                       <ComputerDesktopIcon className="w-12 h-12 opacity-20" />
                       <p className="mt-4 text-xs">Waiting for jobs...</p>
                     </div>
                   )}
                   <TransactionMonitor jobs={jobs} />
                </div>
                <div className="p-4 bg-gray-900 border-t border-gray-800">
                  <div className="flex items-start gap-3">
                    <ShieldCheckIcon className="w-6 h-6 text-green-500 mt-1" />
                    <div>
                      <h4 className="text-sm font-medium text-white">Native Fail-Safe</h4>
                      <p className="text-xs text-gray-400 mt-1">
                        Running via API. Hash verification enabled. <br/>
                        <span className="text-blue-400">{isMoveMode ? 'Mode: Move (Deletes Original)' : 'Mode: Copy (Keeps Original)'}</span>
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Panel: Destination */}
              <div className="w-full md:w-1/3 bg-gray-900/30 flex flex-col min-h-[200px] md:min-h-0">
                <div className="p-3 bg-gray-900 border-b border-gray-800 text-xs font-semibold text-gray-400 tracking-wider flex justify-between items-center">
                  <span>LIBRARY PREVIEW</span>
                </div>
                <div className="flex-1 p-2 overflow-hidden relative">
                   {!folders.library ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-600 gap-4">
                      <FolderOpenIcon className="w-12 h-12 opacity-50" />
                      <p className="text-sm text-center px-6">Library not found at /media/GNARBOX</p>
                      <button onClick={rescanAll} className="px-4 py-2 bg-gray-800 rounded text-sm hover:bg-gray-700">Refresh</button>
                    </div>
                  ) : (
                    <FileSystemTree files={libraryFiles} rootName={folders.library.split(/[\\/]/).pop() || 'Library'} />
                  )}
                </div>
              </div>
            </main>
          </>
        )}
        
        {activeTab === 'settings' && (
           <div className="p-8 max-w-2xl overflow-y-auto h-full flex flex-col">
             <h2 className="text-2xl font-bold mb-6">Settings</h2>
             <div className="space-y-6 flex-1">
                
                {/* Ignored Extensions */}
                <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
                   <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                      <EyeSlashIcon className="w-5 h-5 text-purple-400" />
                      Ignored Files
                   </h3>
                   <div>
                      <label className="block text-sm text-gray-400 mb-2">Ignore files with these extensions (comma separated):</label>
                      <input 
                        type="text" 
                        value={config.ignoredExtensions.join(', ')}
                        onChange={(e) => {
                           const exts = e.target.value.split(',').map(s => s.trim()).filter(s => s.length > 0);
                           setConfig(prev => ({...prev, ignoredExtensions: exts}));
                        }}
                        className="w-full bg-gray-950 border border-gray-700 rounded p-3 text-sm text-gray-300 focus:border-blue-500 outline-none font-mono"
                        placeholder=".xml, .thm, .lrv"
                      />
                      <p className="text-xs text-gray-500 mt-2">These files will be hidden during scan and ignored during processing.</p>
                   </div>
                </div>

                {/* Backup Settings */}
                <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <ShieldCheckIcon className="w-5 h-5 text-blue-400" />
                    Fail-Safe & Backup
                  </h3>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                       <label className="text-sm text-gray-300">Enable Safety Backup</label>
                       <button 
                         onClick={() => setConfig(prev => ({ ...prev, enableBackup: !prev.enableBackup }))}
                         className={`w-12 h-6 rounded-full transition-colors relative ${config.enableBackup ? 'bg-blue-600' : 'bg-gray-700'}`}
                       >
                         <div className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${config.enableBackup ? 'translate-x-6' : ''}`}></div>
                       </button>
                    </div>
                    
                    {config.enableBackup && (
                      <>
                        <div>
                           <label className="block text-sm text-gray-400 mb-1">Backup Location</label>
                            <div className="flex gap-2">
                             <input type="text" value={folders.backup || "Not Connected"} disabled className="flex-1 bg-gray-950 border border-gray-700 rounded p-2 text-sm text-gray-300" />
                           </div>
                        </div>
                        <div>
                           <label className="block text-sm text-gray-400 mb-1">Retention Period (Days)</label>
                           <input type="number" value={config.backupRetentionDays} disabled className="w-24 bg-gray-950 border border-gray-700 rounded p-2 text-sm text-gray-300" />
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {/* Conflict Settings */}
                <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
                  <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <DocumentCheckIcon className="w-5 h-5 text-orange-400" />
                    Duplicate Handling
                  </h3>
                  <div className="space-y-4">
                     <div>
                        <label className="block text-sm text-gray-400 mb-2">When a duplicate file is found in destination:</label>
                        <div className="grid grid-cols-2 gap-2">
                           {[
                             { id: DuplicateStrategy.SKIP, label: 'Skip (Keep Existing)' },
                             { id: DuplicateStrategy.OVERWRITE, label: 'Overwrite' },
                             { id: DuplicateStrategy.RENAME, label: 'Keep Both (Rename)' },
                             { id: DuplicateStrategy.ASK, label: 'Ask for each file' }
                           ].map(opt => (
                             <button
                               key={opt.id}
                               onClick={() => setConfig(prev => ({ ...prev, duplicateStrategy: opt.id as DuplicateStrategy }))}
                               className={`p-3 text-sm rounded border text-left ${
                                 config.duplicateStrategy === opt.id 
                                 ? 'bg-blue-600/20 border-blue-500 text-blue-200' 
                                 : 'bg-gray-950 border-gray-700 text-gray-400 hover:bg-gray-800'
                               }`}
                             >
                               {opt.label}
                             </button>
                           ))}
                        </div>
                     </div>
                  </div>
                </div>

                {/* Pattern Settings */}
                <div className="p-6 bg-gray-900 rounded-lg border border-gray-800">
                  <h3 className="text-lg font-medium mb-4">Pattern Recognition</h3>
                  <p className="text-sm text-gray-400 mb-4">
                    Files are organized based on the following pattern: <br/>
                    <code className="text-blue-400 bg-gray-950 px-1 rounded">YYYY-MM-DD_CameraModel_OriginalName.Ext</code>
                  </p>
                  <div>
                       <label className="block text-sm text-gray-400 mb-1">Folder Structure</label>
                       <input type="text" value={config.organizationPattern} disabled className="w-full bg-gray-950 border border-gray-700 rounded p-2 text-sm text-gray-300 font-mono" />
                    </div>
                </div>
             </div>
             
             {/* Copyright Footer */}
             <div className="mt-8 pt-8 border-t border-gray-800 text-center text-xs text-gray-600">
               <p>&copy; {new Date().getFullYear()} OpenGNARBOX Source-Available Project. All rights reserved.</p>
               <p className="mt-1">Built with React + Vite</p>
             </div>
           </div>
        )}

        {activeTab === 'browse' && <FileBrowser />}
      </div>
    </div>
  );
}

const SidebarItem = ({ icon, label, active, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick: () => void }) => (
  <button 
    onClick={onClick}
    className={`w-full flex items-center space-x-3 px-3 py-2 rounded-md transition-colors ${
      active 
        ? 'bg-blue-600/10 text-blue-400' 
        : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
    }`}
  >
    {icon}
    <span className="text-sm font-medium">{label}</span>
  </button>
);