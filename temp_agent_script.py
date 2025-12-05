import sys
import time
import collections
import heapq

def solve():
    start_time = time.time()
    
    # --- 1. LOAD DATA ---
    try:
        with open('graphs', 'r') as f:
            raw = f.read().split()
        iterator = iter(raw)
        try:
            n = int(next(iterator))
            m = int(next(iterator))
        except StopIteration:
            return
            
        edges_G = []
        for _ in range(m):
            edges_G.append((int(next(iterator)), int(next(iterator))))
            
        remaining = list(iterator)
        idx = 0
        if len(remaining) >= 2 + 2*m:
            try:
                if int(remaining[0]) == n and int(remaining[1]) == m:
                    idx = 2
            except:
                pass
        
        edges_H = []
        while idx + 1 < len(remaining):
            edges_H.append((int(remaining[idx]), int(remaining[idx+1])))
            idx += 2
            
        min_node = float('inf')
        for u, v in edges_G:
            min_node = min(min_node, u, v)
        if min_node == float('inf'): min_node = 1
        offset = min_node
        
        adj_G = [[] for _ in range(n)]
        adj_H = [[] for _ in range(n)]
        deg_G = [0]*n
        deg_H = [0]*n
        
        for u, v in edges_G:
            u_, v_ = u - offset, v - offset
            adj_G[u_].append(v_)
            adj_G[v_].append(u_)
            deg_G[u_] += 1
            deg_G[v_] += 1
            
        for u, v in edges_H:
            u_, v_ = u - offset, v - offset
            adj_H[u_].append(v_)
            adj_H[v_].append(u_)
            deg_H[u_] += 1
            deg_H[v_] += 1
            
        print(f"N={n}, M={m}. WL Init...")

        # --- 2. WL INIT (8 Iters) ---
        colors_G = tuple(deg_G)
        colors_H = tuple(deg_H)
        
        for _ in range(8):
            new_G = []
            for i in range(n):
                neighs = sorted([colors_G[x] for x in adj_G[i]])
                new_G.append(hash((colors_G[i], tuple(neighs))))
            colors_G = tuple(new_G)
            
            new_H = []
            for i in range(n):
                neighs = sorted([colors_H[x] for x in adj_H[i]])
                new_H.append(hash((colors_H[i], tuple(neighs))))
            colors_H = tuple(new_H)
            
        colors_G = list(colors_G)
        colors_H = list(colors_H)

        # --- 3. INCREMENTAL STRUCTURES ---
        buckets_G = collections.defaultdict(set)
        buckets_H = collections.defaultdict(set)
        
        for i in range(n):
            buckets_G[colors_G[i]].add(i)
            buckets_H[colors_H[i]].add(i)
            
        exact_colors = set()
        active_colors = set(buckets_G.keys()) & set(buckets_H.keys())
        
        pq = [] # Min-heap of (size, color)
        
        for c in active_colors:
            sG = len(buckets_G[c])
            sH = len(buckets_H[c])
            if sG == 1 and sH == 1:
                exact_colors.add(c)
            elif sG > 0 and sH > 0:
                heapq.heappush(pq, (sG + sH, c))
        
        mapping = [-1] * n
        used_H = [False] * n
        mapped_count = 0
        
        g_by_degree = sorted(range(n), key=lambda x: deg_G[x], reverse=True)
        h_by_degree = sorted(range(n), key=lambda x: deg_H[x], reverse=True)
        ptr_g_deg = 0
        ptr_h_deg = 0

        def check_color_status(c):
            sG = len(buckets_G[c])
            sH = len(buckets_H[c])
            
            if sG == 0 or sH == 0:
                if c in exact_colors: exact_colors.remove(c)
                return
                
            if sG == 1 and sH == 1:
                exact_colors.add(c)
            else:
                if c in exact_colors: exact_colors.remove(c)
                heapq.heappush(pq, (sG + sH, c))

        loop_iter = 0
        TIME_SOFT_LIMIT = 53.0
        
        while mapped_count < n:
            loop_iter += 1
            elapsed = time.time() - start_time
            if elapsed > 55.0:
                print("Time limit.")
                break
            
            if loop_iter % 10000 == 0:
                 print(f"Iter {loop_iter}: Mapped {mapped_count}/{n}")

            pending = []
            
            if exact_colors:
                c = exact_colors.pop()
                if len(buckets_G[c]) == 1 and len(buckets_H[c]) == 1:
                    u = list(buckets_G[c])[0]
                    v = list(buckets_H[c])[0]
                    pending.append((u, v))
            else:
                # Stall
                best_c = None
                while pq:
                    size, c = heapq.heappop(pq)
                    sG = len(buckets_G[c])
                    sH = len(buckets_H[c])
                    if sG + sH == size and sG > 0 and sH > 0:
                        best_c = c
                        break
                
                if best_c is not None:
                    # Velocity Control
                    remaining_time = max(0.1, TIME_SOFT_LIMIT - elapsed)
                    nodes_left = n - mapped_count
                    rate_needed = nodes_left / remaining_time
                    
                    capacity = 2500.0
                    
                    if rate_needed < capacity * 0.8:
                        min_batch = 1
                    else:
                        min_batch = int(rate_needed / capacity) + 1
                        if min_batch > 100: min_batch = 100
                    
                    g_nodes = list(buckets_G[best_c])
                    h_nodes = list(buckets_H[best_c])
                    limit = min(len(g_nodes), len(h_nodes), min_batch)
                    for k in range(limit):
                        pending.append((g_nodes[k], h_nodes[k]))
                else:
                    # Jump
                    count = 0
                    target = 1 
                    while ptr_g_deg < n and ptr_h_deg < n and count < target:
                        while ptr_g_deg < n and mapping[g_by_degree[ptr_g_deg]] != -1:
                            ptr_g_deg += 1
                        while ptr_h_deg < n and used_H[h_by_degree[ptr_h_deg]]:
                            ptr_h_deg += 1
                        if ptr_g_deg < n and ptr_h_deg < n:
                            pending.append((g_by_degree[ptr_g_deg], h_by_degree[ptr_h_deg]))
                            count += 1
                            ptr_g_deg += 1
                            ptr_h_deg += 1
                        else:
                            break
            
            if not pending:
                break
                
            for u, v in pending:
                if mapping[u] != -1 or used_H[v]:
                    continue
                    
                # Remove
                old_cG = colors_G[u]
                buckets_G[old_cG].remove(u)
                check_color_status(old_cG)
                
                old_cH = colors_H[v]
                buckets_H[old_cH].remove(v)
                check_color_status(old_cH)
                
                mapping[u] = v
                used_H[v] = True
                mapped_count += 1
                
                # Neighbors
                for nu in adj_G[u]:
                    if mapping[nu] == -1:
                        old_c = colors_G[nu]
                        buckets_G[old_c].remove(nu)
                        check_color_status(old_c)
                        
                        new_c = hash((old_c, v))
                        colors_G[nu] = new_c
                        buckets_G[new_c].add(nu)
                        check_color_status(new_c)
                        
                for nv in adj_H[v]:
                    if not used_H[nv]:
                        old_c = colors_H[nv]
                        buckets_H[old_c].remove(nv)
                        check_color_status(old_c)
                        
                        new_c = hash((old_c, v))
                        colors_H[nv] = new_c
                        buckets_H[new_c].add(nv)
                        check_color_status(new_c)

        leftover_H = [x for x in range(n) if not used_H[x]]
        idx_h = 0
        for i in range(n):
            if mapping[i] == -1:
                if idx_h < len(leftover_H):
                    mapping[i] = leftover_H[idx_h]
                    idx_h += 1
                    
        final_ans = [x + offset for x in mapping]
        with open('ans', 'w') as f:
            f.write(" ".join(map(str, final_ans)))
            
        print(f"Done. Mapped {mapped_count} logic.")

    except Exception as e:
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    solve()