import json
import re
from typing import Any, Dict, Optional

from src.core.mindmup_parser import MindmupParser
from src.model.gdrive_model import SearchQuery
from src.model.mindmup_model import Mindmup, MindmupNode
from src.utility.logger import get_logger

logger = get_logger(__name__)

# Threshold for switching read_mindmap from "full content" to "outline + drill-down" mode.
# Tuned empirically:
# - 100KB serialized JSON ~= 25-50k tokens (mixed Chinese/English)
# - MCP hard limit ~= 50-100k tokens, so 100KB leaves headroom for outline + metadata
# - Measured against ai_dict (not raw mindmup file) because to_ai_dict() strips ~70%
#   of original styling noise; raw size is not a fair indicator of AI-facing payload
AI_DICT_SIZE_LIMIT_BYTES = 100 * 1024

# Limits for tree_outline in outline_only mode.
# A full outline of 1000+ node mindmaps can reach 50-160KB, easily exceeding
# the MCP tool result token limit. outline_only already has section_stats for
# navigation, so the outline only needs the first few levels.
OUTLINE_ONLY_MAX_DEPTH = 3
OUTLINE_ONLY_MAX_LINES = 500

# Default title truncation for tree_outline in both "full" and "outline_only" modes.
# MindMup testcase titles often contain long qualifying clauses (e.g. transfer limits,
# date ranges). 80 chars truncated mid-clause makes near-duplicate titles indistinguishable.
OUTLINE_TITLE_MAX_LENGTH = 120

# Upper bound for caller-specified outline depth. render_tree_outline already
# has max_lines=500 as a safety net, but capping depth avoids generating a
# response that's within line count but still exceeds the MCP token limit.
MAX_DEPTH_LIMIT = 10

# Top-K heaviest sections exposed as ready-to-use drill paths. Why 5:
# enough breadth without overwhelming AI context.
OUTLINE_ONLY_SUGGESTED_K = 5


class ReadToolsMixin:
    """Read-only MCP tool methods. Mixed into MCPServer for file organization.

    Methods here use self._get_gdrive_feature_from_header(),
    self._attach_meta(), self._find_file_by_name(), and
    self._fetch_and_parse_mindmup() — all defined on MCPServer (mcp_server.py).
    """

    async def _process_mindmup_content(self, file_id: str, mindmup: Mindmup) -> Dict[str, Any]:
        """Build the read_mindmap response from an already-parsed Mindmup.

        Size-based strategy (threshold = AI_DICT_SIZE_LIMIT_BYTES):
        - Small (ai_dict serialized < limit): tree_outline + full ai_dict (root_node)
        - Large (ai_dict serialized >= limit): tree_outline + section_stats + drill-down hint
          (caller must use get_mindmap_section to fetch actual content)
        """
        result = {
            "title": mindmup.title,
            "id": mindmup.id,
            "format_version": mindmup.format_version,
            "node_count": mindmup.get_node_count(),
            "metadata": {
                "created_time": mindmup.created_time.isoformat() if mindmup.created_time else None,
                "modified_time": mindmup.modified_time.isoformat() if mindmup.modified_time else None,
                "author": mindmup.author
            },
        }

        # Measure the actual serialized size of ai_dict (not a heuristic like
        # node_count * estimated_bytes_per_node). Earlier heuristics underestimated
        # content-rich mindmaps with long titles or notes, causing the MCP response
        # to exceed the token limit and fail the read.
        ai_dict = mindmup.root_node.to_ai_dict()
        ai_dict_size = len(json.dumps(ai_dict, ensure_ascii=False).encode('utf-8'))

        # Decide return strategy: full content vs outline-only navigation
        if ai_dict_size < AI_DICT_SIZE_LIMIT_BYTES:
            # Small enough to ship in one response. AI traverses root_node directly.
            result["content_type"] = "full"
            result["root_node"] = ai_dict
            result["tree_outline"] = MindmupParser.render_tree_outline(
                mindmup.root_node, max_title_length=OUTLINE_TITLE_MAX_LENGTH
            )
        else:
            # Too large. Ship navigation aids only — AI must drill down explicitly.
            # This forces grounded answers (AI cannot fabricate content it never fetched).
            result["content_type"] = "outline_only"
            result["tree_outline"] = MindmupParser.render_tree_outline(
                mindmup.root_node,
                max_depth=OUTLINE_ONLY_MAX_DEPTH,
                max_lines=OUTLINE_ONLY_MAX_LINES,
                max_title_length=OUTLINE_TITLE_MAX_LENGTH,
            )
            result["section_stats"] = MindmupParser.get_section_stats(mindmup.root_node)
            sorted_stats = sorted(
                result["section_stats"],
                key=lambda s: s["text_weight"],
                reverse=True,
            )
            result["suggested_start_paths"] = [
                s["path"] for s in sorted_stats[:OUTLINE_ONLY_SUGGESTED_K]
            ]
            result["message"] = (
                f"This mindmap is too large to return in full "
                f"(ai_dict serialized = {ai_dict_size:,} bytes / "
                f"~{ai_dict_size // 1024} KB, {mindmup.get_node_count()} nodes; "
                f"limit = {AI_DICT_SIZE_LIMIT_BYTES // 1024} KB). "
                f"Start with one of `suggested_start_paths` (Top-{OUTLINE_ONLY_SUGGESTED_K} "
                f"by text_weight) and call "
                f"get_mindmap_section(file_id='{file_id}', node_path='<path>'). "
                f"Do not guess content - only report what you read via drill-down."
            )

        return result

    async def list_files(
            self, max_result: int = 1000, name_contain: Optional[str] = None,
            mindmup_only: bool = True,
    ) -> Dict[str, Any]:
        """List MindMup files from Google Drive with their parent folder URL.

        When to use: When you need to find MindMup file IDs and the Drive folder
        URL where each file lives. Folders and non-MindMup files are excluded by default.

        Display rule: Show 'folder_url' as PLAIN TEXT URL exactly as returned.
        Do NOT wrap it in markdown link syntax like [open](url) or [link](url).

        Args:
            max_result: Max files to return (default 1000).
            name_contain: Filter by name (partial match).
            mindmup_only: If True (default), exclude folders and non-MindMup files.
        """
        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()
            query = SearchQuery(
                max_result=max_result,
                name_contain=name_contain,
            )
            result = await gdrive_feature.list_file(query=query)
            if not result.is_success:
                return {"error": result.detail}

            files = []
            for f in result.detail.get('files', []):
                if mindmup_only and not f.is_mindmup():
                    continue
                folder_url = (
                    f"https://drive.google.com/drive/folders/{f.parents[0]}"
                    if f.parents else None
                )
                files.append({
                    "id": f.id,
                    "name": f.name,
                    "folder_url": folder_url,
                    "mime_type": f.mime_type,
                    "size": f.size,
                    "modified_time": f.modified_time.isoformat() if f.modified_time else None,
                    "shared": f.shared,
                })

            return self._attach_meta({
                "files": files,
                "files_total_count": len(files),
                "next_page_token": result.detail.get('next_page_token'),
            })

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f'list_files error: {e}')
            return {"error": str(e)}

    async def read_mindmap(
            self, file_id: Optional[str] = None, file_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read a mindmap file from Google Drive.

        When to use: ALWAYS start here when you need to read or understand a mindmap.
        This is the primary and only tool for reading mindmap content.

        Returns:
        - Small files (ai_dict < 100KB serialized): full AI-friendly content + tree outline
        - Large files (ai_dict >= 100KB): tree outline + section stats only
          -> use get_mindmap_section(node_path) to drill into specific sections

        Args:
            file_id: Google Drive file ID.
            file_name: File name to search for (uses first match). Provide one of file_id or file_name.
        """
        if not file_id and not file_name:
            return {"error": "Provide file_id or file_name."}

        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            if file_name and not file_id:
                file_id = await self._find_file_by_name(gdrive_feature, file_name)
                if not file_id:
                    return {"error": f"No MindMup file found matching '{file_name}'."}

            file_metadata = await gdrive_feature.get_file_metadata(file_id)
            file_size = int(file_metadata.get('size', 0)) if file_metadata else 0

            mindmup, _, error = await self._fetch_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            mindmap_data = await self._process_mindmup_content(file_id, mindmup)

            if file_size > 0:
                mindmap_data["file_size_mb"] = round(file_size / (1024 * 1024), 2)

            mindmap_data["file_id"] = file_id
            mindmap_data["file_name"] = file_metadata.get('name', '')

            return self._attach_meta(mindmap_data)

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f'read_mindmap error: {e}')
            return {"error": str(e)}

    async def search_mindmap(
            self,
            file_id: str,
            keyword: str,
            max_results: int = 30,
            normalize_whitespace: bool = True,
            node_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search for nodes in a mindmap by keyword.

        When to use: When you need to find specific testcases, steps, or content by keyword.
        Returns matching nodes with their node_path for follow-up with get_mindmap_section.

        Args:
            file_id: Google Drive file ID.
            keyword: Search keyword (case-insensitive partial match).
            max_results: Max results to return (default 30).
            normalize_whitespace: If True (default), strip all whitespace from both
                keyword and title before matching. "N 類" matches "N類". Set False
                for whitespace-exact matching.
            node_path: Optional. Restrict search to a subtree (e.g. "1.2.3").
                Useful when get_mindmap_section returned outline_only for a large
                subtree - search within it instead of fetching the full content.
        """
        if node_path and not re.match(r"^\d+(\.\d+)*$", node_path):
            return {"error": f"node_path must be a dotted integer path like '1.2.3', got '{node_path}'"}

        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            mindmup, file_content, error = await self._fetch_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            # Resolve search scope
            if node_path:
                search_root = MindmupParser.find_node_by_path(mindmup.root_node, node_path)
                if search_root is None:
                    return {"error": f"node_path '{node_path}' not found in mindmap."}
                search_prefix = node_path
                search_ancestors = []
            else:
                search_root = mindmup.root_node
                search_prefix = "1"
                search_ancestors = None

            results = []

            def _normalize(text: str) -> str:
                text = text.lower()
                if normalize_whitespace:
                    text = "".join(text.split())
                return text

            keyword_normalized = _normalize(keyword)

            title_preview_chars = 100

            def _search(node: MindmupNode, prefix: str = "1",
                        ancestors: Optional[list] = None) -> None:
                if ancestors is None:
                    ancestors = []
                if len(results) >= max_results:
                    return
                if keyword_normalized in _normalize(node.title):
                    breadcrumb = [t for t in ancestors if t and t.strip()]
                    results.append({
                        "node_path": prefix,
                        "title_preview": node.to_outline_line(title_preview_chars),
                        "breadcrumb": breadcrumb,
                        "children_count": len(node.children),
                    })
                next_ancestors = ancestors + [node.to_outline_line()]
                for i, child in enumerate(node.children, start=1):
                    _search(child, f"{prefix}.{i}", next_ancestors)

            _search(search_root, search_prefix,
                    search_ancestors if search_ancestors is not None else None)

            response = {
                "file_id": file_id,
                "keyword": keyword,
                "search_scope": node_path,
                "total_found": len(results),
                "results": results,
                "hint": "Use get_mindmap_section(file_id, node_path) to read full content of a matched node.",
            }
            return self._attach_meta(response)

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f'search_mindmap error: {e}')
            return {"error": str(e)}

    async def get_mindmap_section(
            self,
            file_id: str,
            node_path: str,
            max_depth: Optional[int] = None,
            offset: int = 0,
            limit: int = 0,
    ) -> Dict[str, Any]:
        """Get a specific section of a mindmap by node path.

        When to use: After read_mindmap returns tree_outline for a large file,
        use the node_path (e.g. "1.2.3") to drill into a specific section.

        Args:
            file_id: Google Drive file ID.
            node_path: Dotted path like "1.2.3".
            max_depth: If set (>=1), overrides the default outline depth
                for the outline_only fallback. Clamped to MAX_DEPTH_LIMIT (10).
                Ignored when subtree fits within the size limit (full mode).
            offset: Start from the N-th child (0-based). Use with limit for
                pagination when a section has too many children to return at once.
            limit: Max children to return. 0 (default) = return all (existing
                behavior). When > 0 and the subtree is too large, only
                children[offset:offset+limit] are returned with full content.
        """
        if max_depth is not None and max_depth < 1:
            return {"error": f"max_depth must be >= 1 or None, got {max_depth}"}
        if offset < 0:
            return {"error": f"offset must be >= 0, got {offset}"}
        if limit < 0:
            return {"error": f"limit must be >= 0, got {limit}"}

        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            mindmup, file_content, error = await self._fetch_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            target_node = MindmupParser.find_node_by_path(mindmup.root_node, node_path)
            if not target_node:
                return {
                    "error": f"Node path '{node_path}' not found. "
                    f"Use read_mindmap to get tree_outline with valid paths."
                }

            breadcrumb = MindmupParser.get_node_breadcrumb(mindmup.root_node, node_path)

            # Same size guard as read_mindmap: a drilled section can itself be too
            # large (deep subtree with rich content). Measure first; only ship full
            # ai_dict when it fits, otherwise return outline + drill-down hint.
            subtree_ai = target_node.to_ai_dict()
            subtree_size = len(json.dumps(subtree_ai, ensure_ascii=False).encode('utf-8'))

            response: Dict[str, Any] = {
                "file_id": file_id,
                "node_path": node_path,
                "breadcrumb": breadcrumb,
            }

            if subtree_size < AI_DICT_SIZE_LIMIT_BYTES:
                response["content_type"] = "full"
                response["subtree"] = MindmupParser.render_subtree_detail(
                    target_node, node_path, ai_dict=subtree_ai
                )
            else:
                # Subtree too large. Three strategies depending on caller intent:
                if limit > 0 and target_node.children:
                    # Strategy A: Pagination — return a slice of children as full content
                    children_slice = target_node.children[offset:offset + limit]
                    sliced_items = []
                    for i, child in enumerate(children_slice, start=offset + 1):
                        child_path = f"{node_path}.{i}"
                        sliced_items.append({
                            "path": child_path,
                            "node": child.to_ai_dict(),
                        })

                    sliced_size = len(json.dumps(sliced_items, ensure_ascii=False).encode('utf-8'))
                    if sliced_size >= AI_DICT_SIZE_LIMIT_BYTES:
                        # Paginated slice still too large — suggest smaller limit or drill deeper
                        effective_depth = (
                            min(max_depth, MAX_DEPTH_LIMIT)
                            if max_depth is not None
                            else OUTLINE_ONLY_MAX_DEPTH
                        )
                        response["content_type"] = "outline_only"
                        response["tree_outline"] = MindmupParser.render_tree_outline(
                            target_node, path_prefix=node_path,
                            max_depth=effective_depth,
                            max_lines=OUTLINE_ONLY_MAX_LINES,
                            max_title_length=OUTLINE_TITLE_MAX_LENGTH,
                        )
                        response["section_stats"] = MindmupParser.get_section_stats(
                            target_node, path_prefix=node_path
                        )

                        # Check if even limit=1 would exceed the limit
                        avg_child_size = sliced_size // max(len(sliced_items), 1)
                        single_child_too_large = avg_child_size >= AI_DICT_SIZE_LIMIT_BYTES
                        if single_child_too_large:
                            response["message"] = (
                                f"Paginated slice (limit={limit}) is still too large "
                                f"({sliced_size:,} bytes; limit = {AI_DICT_SIZE_LIMIT_BYTES // 1024} KB). "
                                f"Each child is individually too large for pagination. "
                                f"Drill deeper into a specific child: "
                                f"get_mindmap_section(file_id='{file_id}', node_path='{node_path}.N')."
                            )
                        else:
                            response["message"] = (
                                f"Paginated slice (limit={limit}) is still too large "
                                f"({sliced_size:,} bytes; limit = {AI_DICT_SIZE_LIMIT_BYTES // 1024} KB). "
                                f"Try limit=1 to read one child at a time, or drill deeper "
                                f"with node_path='{node_path}.N'."
                            )
                    else:
                        total_children = len(target_node.children)
                        next_offset = offset + limit
                        response["content_type"] = "paginated"
                        response["children"] = sliced_items
                        response["pagination"] = {
                            "offset": offset,
                            "limit": limit,
                            "total_children": total_children,
                            "has_more": next_offset < total_children,
                            "next_offset": next_offset if next_offset < total_children else None,
                        }
                        response["message"] = (
                            f"Showing children {offset + 1}-{min(offset + limit, total_children)} "
                            f"of {total_children}. "
                            + (f"Call get_mindmap_section(file_id='{file_id}', "
                               f"node_path='{node_path}', offset={next_offset}, limit={limit}) "
                               f"for next page."
                               if next_offset < total_children else "This is the last page.")
                        )

                elif not target_node.children:
                    # Strategy B: Truncation — leaf node too heavy, truncate content
                    full_json = json.dumps(subtree_ai, ensure_ascii=False, indent=2)
                    truncate_at = AI_DICT_SIZE_LIMIT_BYTES
                    truncated = full_json[:truncate_at]
                    response["content_type"] = "truncated"
                    response["subtree_text"] = truncated
                    response["truncation"] = {
                        "original_bytes": subtree_size,
                        "returned_bytes": len(truncated.encode('utf-8')),
                        "is_complete": False,
                    }
                    response["message"] = (
                        f"Section '{node_path}' is a leaf node with {subtree_size:,} bytes "
                        f"(limit = {AI_DICT_SIZE_LIMIT_BYTES // 1024} KB). "
                        f"Content truncated. First {truncate_at // 1024} KB returned."
                    )

                else:
                    # Strategy C: Original outline_only — has children, caller didn't request pagination
                    effective_depth = (
                        min(max_depth, MAX_DEPTH_LIMIT)
                        if max_depth is not None
                        else OUTLINE_ONLY_MAX_DEPTH
                    )
                    response["content_type"] = "outline_only"
                    response["tree_outline"] = MindmupParser.render_tree_outline(
                        target_node, path_prefix=node_path,
                        max_depth=effective_depth,
                        max_lines=OUTLINE_ONLY_MAX_LINES,
                        max_title_length=OUTLINE_TITLE_MAX_LENGTH,
                    )
                    response["section_stats"] = MindmupParser.get_section_stats(
                        target_node, path_prefix=node_path
                    )
                    response["message"] = (
                        f"Section '{node_path}' is still too large "
                        f"(ai_dict serialized = {subtree_size:,} bytes / "
                        f"~{subtree_size // 1024} KB; limit = {AI_DICT_SIZE_LIMIT_BYTES // 1024} KB; "
                        f"outline depth = {effective_depth}). "
                        f"Options: (1) drill deeper with node_path='{node_path}.N', "
                        f"(2) paginate with offset=0, limit=20 to read children in batches, "
                        f"(3) search within with search_mindmap(file_id='{file_id}', "
                        f"keyword='...', node_path='{node_path}')."
                    )

            return self._attach_meta(response)

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f'get_mindmap_section error: {e}')
            return {"error": str(e)}
