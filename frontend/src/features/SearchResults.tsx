import React from 'react';
import { MovieCard } from '../components/movies/Cards';
import { Movie } from '../types';

export const SearchResults = ({ query, results, onMovieSelect }: { query: string; results: Movie[]; onMovieSelect: (m: Movie) => void }) => { 
  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12"> 
      <div className="mb-8"> 
        <h1 className="text-3xl md:text-5xl font-['Noto_Sans_SC'] font-bold text-white mb-4">"{query}" <span className="text-gray-500 font-['Orbitron'] text-2xl">SEARCH_RESULTS</span></h1> 
      </div> 
      <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center"> {results.map((movie) => (<MovieCard key={movie.id} movie={movie} category={{ colorClass: 'border-white/20' }} onClick={onMovieSelect} />))} </div> 
    </div>
  ); 
};
