"""Cheap necessary conditions for forward play and admissible search bounds.

Passing these checks does not prove a legal continuation exists. They never
select moves or replace legal search, and ignore blockers to stay optimistic.
"""
from functools import lru_cache
import chess


def forward_material_possible(source,target):
    """Captures cannot add men or pawns; pawns need distinct forward origins."""
    for color in chess.COLORS:
        if target.occupied_co[color].bit_count()>source.occupied_co[color].bit_count():return False
        origins=list(chess.scan_forward(source.pawns & source.occupied_co[color]))
        goals=list(chess.scan_forward(target.pawns & target.occupied_co[color]))
        if len(goals)>len(origins):return False
        choices=[]
        for goal in goals:
            allowed=[]
            for index,origin in enumerate(origins):
                advance=(chess.square_rank(goal)-chess.square_rank(origin))*(1 if color else -1)
                if advance>=abs(chess.square_file(goal)-chess.square_file(origin)):allowed.append(index)
            if not allowed:return False
            choices.append(allowed)
        # Bipartite matching prevents one pawn explaining two target pawns.
        assigned={}
        def assign(goal,seen):
            for origin in choices[goal]:
                if origin in seen:continue
                seen.add(origin)
                if origin not in assigned or assign(assigned[origin],seen):
                    assigned[origin]=goal;return True
            return False
        if not all(assign(goal,set()) for goal in sorted(range(len(goals)),key=lambda goal:len(choices[goal]))):return False
    return True


@lru_cache(maxsize=64)
def knight_distances(origin):
    distances=[64]*64;distances[origin]=0;frontier=chess.BB_SQUARES[origin];seen=frontier;distance=0
    while frontier:
        distance+=1;following=0
        for square in chess.scan_forward(frontier):following|=chess.BB_KNIGHT_ATTACKS[square]
        frontier=following & ~seen;seen|=frontier
        for square in chess.scan_forward(frontier):distances[square]=distance
    return tuple(distances)


def travel_cost(piece,origin,goal,color):
    dx=abs(chess.square_file(origin)-chess.square_file(goal))
    dy=abs(chess.square_rank(origin)-chess.square_rank(goal))
    if origin==goal:return 0
    if piece==chess.PAWN:
        advance=(chess.square_rank(goal)-chess.square_rank(origin))*(1 if color else -1)
        if advance<dx or advance<=0:return 64
        double=(chess.square_rank(origin)==(1 if color else 6) and advance>=2 and dx<=advance-2)
        return advance-int(double)
    if piece==chess.KNIGHT:return knight_distances(origin)[goal]
    if piece==chess.KING:return max(dx,dy)
    if piece==chess.BISHOP:
        if (dx+dy)%2:return 64
        return 1 if dx==dy else 2
    if piece==chess.ROOK:return 1 if not dx or not dy else 2
    return 1 if not dx or not dy or dx==dy else 2


class TravelBound:
    """Minimum piece travel, allowing reuse of origins and ignoring blockers.

    Reusing an origin weakens the bound but keeps it cheap and admissible.
    Promotions and castling are relaxed explicitly; no path is ranked away.
    """
    def __init__(self,target):
        goals={(piece,color):tuple(chess.scan_forward(target.pieces_mask(piece,color)))
               for color in chess.COLORS for piece in chess.PIECE_TYPES}
        # Capture only immutable goal data, avoiding a bound-method/cache
        # reference cycle that would retain a finished search's large cache.
        @lru_cache(maxsize=16384)
        def minimum(piece,color,origins):
            squares=goals[piece,color]
            if not squares:return 0
            if not origins:return 64
            return sum(min(travel_cost(piece,origin,goal,color) for origin in chess.scan_forward(origins))
                       for goal in squares)
        self._cost=minimum

    def possible(self,state,white_turns,black_turns):
        for color,turns in ((chess.WHITE,white_turns),(chess.BLACK,black_turns)):
            pawns=state.pieces_mask(chess.PAWN,color)
            cost=self._cost(chess.PAWN,color,pawns)
            if cost>turns:return False
            # Even one promotion could supply a missing piece, so ignore
            # non-pawn travel whenever a promotion might fit this budget.
            promotion_possible=any((7-chess.square_rank(square) if color else chess.square_rank(square))
                -int(chess.square_rank(square)==(1 if color else 6))<=turns
                for square in chess.scan_forward(pawns))
            if promotion_possible:continue
            castling=bool(state.castling_rights & state.occupied_co[color])
            for piece in (chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN,chess.KING):
                if piece==chess.KING and castling:continue
                cost+=self._cost(piece,color,state.pieces_mask(piece,color))
            # A castle can move the rook for free in this relaxed count.
            if cost-int(castling)>turns:return False
        return True
