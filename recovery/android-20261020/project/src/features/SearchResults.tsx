import React from 'react';
import { MovieCard } from '../components/movies/Cards';
import { Movie } from '../types';
import { AggregateSearch } from './aggregator/AggregateSearch';

export const SearchResults = ({ query, results, onMovieSelect }: { query: string; results: Movie[]; onMovieSelect: (m: Movie) => void }) => {
  const count = results.length;
  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12">
      <div className="mb-8">
        <h1 className="text-3xl md:text-5xl font-['Noto_Sans_SC'] font-bold text-white mb-2">
          “{query}” <span className="text-gray-500 font-['Noto_Sans_SC'] text-xl md:text-2xl">的搜索结果</span>
        </h1>
        <p className="text-sm text-gray-400 font-['Noto_Sans_SC']">共找到 {count} 部影片</p>
      </div>
      {count > 0 ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center">
          {results.map((movie) => (
            <MovieCard key={movie.id} movie={movie} category={{ colorClass: 'border-white/20' }} onClick={onMovieSelect} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <p className="text-lg text-gray-300 font-['Noto_Sans_SC'] mb-2">没有找到相关影片</p>
          <p className="text-sm text-gray-500 font-['Noto_Sans_SC']">本地库无结果，已自动为你聚合搜索外部资源站</p>
        </div>
      )}
      {/* 本地库无结果时自动触发聚合搜索（仅默认源，其他源手动切）。query 为 key 保证换词重搜。 */}
      {count === 0 && query.trim() && <AggregateSearch key={query} query={query} />}
    </div>
  );
};
