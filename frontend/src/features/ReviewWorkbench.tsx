import React, { useState, useEffect } from 'react';
import { ShieldAlert, Database, Video, Loader2, Layout, Archive } from 'lucide-react';
import { ResourceGovernance } from './ResourceGovernance';
import { EpisodeDiagnostics } from './EpisodeDiagnostics';
import { OtherVideosArchive } from './OtherVideosArchive';
import { movieService } from '../api';

const SUPPORTED_BUCKETS = ['resource_governance', 'episode_review', 'other_videos_archive'];

export const ReviewWorkbench = () => {
  const [activeTab, setActiveTab] = useState<string>('resource_governance');
  const [taxonomy, setTaxonomy] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchTaxonomy = async () => {
      setLoading(true);
      try {
        const data = await movieService.getReviewTaxonomy();
        setTaxonomy(data);
        if (data?.buckets?.length > 0) {
           const firstReviewBucket = data.buckets.find((b: any) => SUPPORTED_BUCKETS.includes(b.id));
           if (firstReviewBucket) setActiveTab(firstReviewBucket.id);
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    };
    fetchTaxonomy();
  }, []);

  const getIconForBucket = (id: string) => {
    switch (id) {
       case 'resource_governance': return <Database className="w-4 h-4" />;
       case 'episode_review': return <Video className="w-4 h-4" />;
       case 'other_videos_archive': return <Archive className="w-4 h-4" />;
       default: return <Layout className="w-4 h-4" />;
    }
  };

  const getLabelForBucket = (id: string, defaultLabel?: string) => {
    if (defaultLabel) return defaultLabel;
    switch (id) {
       case 'resource_governance': return '资源治理控制面板';
       case 'episode_review': return '剧集质量诊断';
       case 'other_videos_archive': return '其他视频归档';
       default: return id;
    }
  };

  return (
    <div className="min-h-screen w-full pt-20 px-4 md:px-12 pb-12 bg-[#050505] font-mono">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="p-2 border border-primary text-primary shadow-primary bg-primary-10">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-widest flex items-center gap-4">
            SYSTEM <span className="text-primary">GOVERNANCE</span>
          </h1>
          <div className="text-[10px] text-primary-50 mt-1 uppercase tracking-[0.3em]">CyberStream Governance Center v1.21</div>
        </div>
        <div className="flex-grow h-[1px] bg-gradient-to-r from-primary/50 to-transparent"></div>
      </div>

      {loading && !taxonomy ? (
        <div className="flex items-center gap-2 text-primary-50">
           <Loader2 className="animate-spin w-4 h-4" /> 正在加载数据...
        </div>
      ) : null}

      <div className="flex flex-wrap gap-4 mb-6">
        {SUPPORTED_BUCKETS.map(id => {
          // If we have taxonomy, try to find a backend label
          const bucket = taxonomy?.buckets?.find((b: any) => b.id === id);
          return (
          <button 
            key={id}
            onClick={() => setActiveTab(id)}
            className={`flex items-center justify-center gap-2 flex-col sm:flex-row py-3 px-6 text-sm font-bold tracking-widest uppercase transition-colors ${activeTab === id ? 'bg-primary text-black border-b-2 border-white' : 'bg-primary-5 text-primary border border-primary-30 hover:bg-primary-10'}`}
          >
            {getIconForBucket(id)}
            {getLabelForBucket(id, bucket?.label)}
          </button>
        )})}
      </div>

      <div className="mt-4">
        {activeTab === 'resource_governance' && <ResourceGovernance taxonomy={taxonomy} />}
        {activeTab === 'episode_review' && <EpisodeDiagnostics taxonomy={taxonomy} />}
        {activeTab === 'other_videos_archive' && <OtherVideosArchive />}
      </div>
    </div>
  );
};
