import random
from collections import Counter
from typing import Dict, List

from .random import Random
from .recommender import Recommender


class MostCommon(Recommender):
    def __init__(
            self,
            tracks_redis,
            tracks_with_diverse_recs_redis,
            artists_redis,
            catalog,
            recommendations_ub_redis,
            recommendations_redis,
            listened: Dict[int, List[int]],
            prev_recs: Dict[int, Dict[str, List[int]]]
    ):
        self.tracks_redis = tracks_redis
        self.tracks_with_diverse_recs_redis = tracks_with_diverse_recs_redis
        self.artists_redis = artists_redis
        self.catalog = catalog
        self.recommendations_ub_redis = recommendations_ub_redis
        self.recommendations_redis = recommendations_redis
        self.fallback = Random(tracks_redis)
        self.listened = listened
        self.prev_recs = prev_recs

    def _get_recommendations_nn(self, prev_track: int, tracks):
        previous_track = tracks.get(prev_track)
        if previous_track is None:
            return []
        previous_track = self.catalog.from_bytes(previous_track)
        recommendations = previous_track.recommendations
        if recommendations is None:
            return []
        return list(recommendations)

    def _get_recommendations_from_redis(self, user: int, redis):
        recommendations = redis.get(user)
        if recommendations is None:
            return []
        recommendations = list(self.catalog.from_bytes(recommendations))
        return recommendations

    def _get_recommendations_sa(self, prev_track: int):
        previous_track = self.tracks_redis.get(prev_track)
        if previous_track is not None:
            prev_track = self.catalog.from_bytes(previous_track)
            artist_data = self.artists_redis.get(prev_track.artist)
            if artist_data is not None:
                artist_tracks = self.catalog.from_bytes(artist_data)
                return artist_tracks
        return []

    def recommend_next(self, user: int, prev_track: int, prev_track_time: float) -> int:
        self.listened[user] = self.listened.get(user, [])

        if prev_track_time < 0.75 and user in self.prev_recs:
            recommendations = self.prev_recs[user]
        else:
            recommendations = {
                'lf': self._get_recommendations_from_redis(user, self.recommendations_redis),
                'ub': self._get_recommendations_from_redis(user, self.recommendations_ub_redis),
                'nn': self._get_recommendations_nn(prev_track, self.tracks_redis),
                'nn_diverse': self._get_recommendations_nn(prev_track, self.tracks_with_diverse_recs_redis),
                'tp': self.catalog.top_tracks[:100],
                'sa': self._get_recommendations_sa(prev_track)
            }

            # Get recommendations from the top tracks
            recommendations['tp'] = recommendations['tp'] if recommendations['tp'] is not None else []

        tracks_counter = Counter()
        for rec in recommendations.values():
            tracks_counter.update(rec)

        rec_track = self.fallback.recommend_next(user, prev_track, prev_track_time)
        for track in sorted(tracks_counter, key=tracks_counter.get, reverse=True):
            if track in recommendations['nn'] and track not in self.listened[user]:
                rec_track = track
                break
        else:
            mc = tracks_counter.most_common(10)
            random.shuffle(mc)
            for tr, _ in mc:
                if tr not in self.listened[user]:
                    rec_track = tr
                    break

        self.listened[user].append(rec_track)
        self.prev_recs[user] = recommendations
        return rec_track
