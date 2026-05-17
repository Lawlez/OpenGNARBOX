import React, { useState, useEffect } from 'react';
import { 
  FolderIcon, 
  DocumentIcon, 
  ArrowDownTrayIcon,
  ArrowUturnLeftIcon,
  CheckCircleIcon
} from '@heroicons/react/24/outline';
import { fileService } from '../services/FileService';

interface FileInfo {
  name: string;
  isDirectory: boolean;
  path: string;
  size: number;
  createdDate: number;
}

export default function FileBrowser() {
  const [currentPath, setCurrentPath] = useState<string>('/media/GNARBOX');
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadDirectory(currentPath);
  }, [currentPath]);

  const loadDirectory = async (path: string) => {
    setLoading(true);
    try {
      const items = await fileService.listDirectory(path);
      setFiles(items);
      setSelectedPaths(new Set()); // Reset selection on navigate
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const handleNavigateUp = () => {
    const parts = currentPath.split('/').filter(Boolean);
    if (parts.length > 1) { // Prevent going below root
      parts.pop();
      setCurrentPath('/' + parts.join('/'));
    } else if (parts.length === 1) {
      setCurrentPath('/');
    }
  };

  const handleRowClick = (item: FileInfo) => {
    if (item.isDirectory) {
      setCurrentPath(item.path);
    }
  };

  const toggleSelect = (path: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const newSelected = new Set(selectedPaths);
    if (newSelected.has(path)) {
      newSelected.delete(path);
    } else {
      newSelected.add(path);
    }
    setSelectedPaths(newSelected);
  };

  const downloadSelected = async () => {
    if (selectedPaths.size === 0) return;
    
    try {
      const res = await fetch('/api/files/download/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: Array.from(selectedPaths) })
      });
      
      if (!res.ok) throw new Error("Failed to create download session");
      
      const data = await res.json();
      if (data.downloadId) {
        window.location.href = `/api/files/download/${data.downloadId}`;
        setSelectedPaths(new Set());
      }
    } catch (e) {
      console.error("Download error", e);
      alert("Failed to initiate download.");
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '--';
    const mb = bytes / (1024 * 1024);
    if (mb < 1) return (bytes / 1024).toFixed(1) + ' KB';
    return mb.toFixed(1) + ' MB';
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-gray-950 text-slate-200">
      {/* Header */}
      <header className="h-16 border-b border-gray-800 bg-gray-900/50 flex items-center justify-between px-8 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <button 
            onClick={handleNavigateUp}
            disabled={currentPath === '/'}
            className="p-2 hover:bg-gray-800 rounded disabled:opacity-50"
            title="Up Directory"
          >
            <ArrowUturnLeftIcon className="w-5 h-5 text-gray-400" />
          </button>
          <div>
            <h1 className="text-lg font-semibold text-white flex items-center gap-2">
              File Browser
            </h1>
            <p className="text-xs text-gray-400 font-mono mt-1">{currentPath}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">{selectedPaths.size} selected</span>
          <button 
            onClick={downloadSelected}
            disabled={selectedPaths.size === 0}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white rounded-md text-sm font-medium transition-colors shadow-lg shadow-blue-500/20 disabled:shadow-none"
          >
            <ArrowDownTrayIcon className="w-4 h-4" />
            Download ZIP
          </button>
        </div>
      </header>

      {/* File List */}
      <div className="flex-1 overflow-auto p-6 relative">
        {loading && (
          <div className="absolute inset-0 z-10 bg-gray-950/50 flex items-center justify-center">
            <span className="text-gray-400">Loading...</span>
          </div>
        )}

        {files.length === 0 && !loading ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-600">
            <FolderIcon className="w-16 h-16 opacity-20" />
            <span className="mt-4 text-sm">Directory is empty</span>
          </div>
        ) : (
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-left text-sm text-gray-400">
              <thead className="bg-gray-950 border-b border-gray-800 text-xs uppercase font-medium">
                <tr>
                  <th className="px-4 py-3 w-12">
                    <CheckCircleIcon className="w-4 h-4 opacity-50" />
                  </th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Date Modified</th>
                  <th className="px-4 py-3 text-right">Size</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {files.map(f => (
                  <tr 
                    key={f.path}
                    onClick={() => handleRowClick(f)}
                    className={`hover:bg-gray-800/50 transition-colors cursor-pointer ${selectedPaths.has(f.path) ? 'bg-blue-900/10' : ''}`}
                  >
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      <input 
                        type="checkbox" 
                        checked={selectedPaths.has(f.path)}
                        onChange={(e) => toggleSelect(f.path, e as any)}
                        className="w-4 h-4 rounded border-gray-700 bg-gray-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-gray-900 cursor-pointer"
                      />
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-200 flex items-center gap-3">
                      {f.isDirectory ? (
                        <FolderIcon className="w-5 h-5 text-blue-400" />
                      ) : (
                        <DocumentIcon className="w-5 h-5 text-gray-500" />
                      )}
                      <span>{f.name}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(f.createdDate).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {f.isDirectory ? '--' : formatSize(f.size)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
