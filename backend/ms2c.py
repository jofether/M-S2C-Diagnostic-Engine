import os
import re
import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer, ViTModel, ViTImageProcessor
from PIL import Image

"""
=========================================================================================
Multimodal Semantic-to-Code (MS2C) Engine - Unified Scope
=========================================================================================
Architecture: Multi-Stage Cascading Retrieval Pipeline
1. Document Filter: Multi-tiered file routing via CodeBERT + Lexical Matching.
2. Entity Extraction: Dynamic DOM/JSX Tag Parsing (Safe word-in-tag matching).
3. Semantic Scorer: Zero-shot CodeBERT + ViT ranking using contextual path injection.
4. Tensor Boosting: Applies a tiered Dynamic Soft Boost matrix for exact file overrides, 
   tag matches, CSS ClassNames, and deep inline attributes.
=========================================================================================
"""


class MS2CModel(nn.Module):
    """
    Dual-Encoder Multimodal Transformer Architecture.
    Combines CodeBERT (Text/Code) and ViT (Vision) representations into a unified
    vector space, mediated by a dynamic neural gating network.
    """

    def __init__(self, hidden_dim=768):
        super(MS2CModel, self).__init__()
        self.codebert = AutoModel.from_pretrained("microsoft/codebert-base")
        self.vit = ViTModel.from_pretrained("google/vit-base-patch16-224-in21k")

        # Aligns the ViT hidden states to CodeBERT's embedding dimensions
        self.mlp_projection = nn.Sequential(
            nn.Linear(self.vit.config.hidden_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim)
        )

        # Learns to dynamically weigh Text vs Vision confidence
        self.gating_network = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid()
        )

    def forward_text(self, input_ids, attention_mask):
        outputs = self.codebert(input_ids=input_ids, attention_mask=attention_mask)
        return torch.nn.functional.normalize(outputs.last_hidden_state[:, 0, :], p=2, dim=1)

    def forward_image(self, pixel_values):
        outputs = self.vit(pixel_values=pixel_values)
        projected_embedding = self.mlp_projection(outputs.last_hidden_state[:, 0, :])
        return torch.nn.functional.normalize(projected_embedding, p=2, dim=1)

    def compute_gating_weight(self, text_emb, visual_emb):
        return self.gating_network(torch.cat([text_emb, visual_emb], dim=1))


class MS2CRetriever:
    """
    The orchestrator class for the Retrieve-then-Rerank MS2C pipeline.
    Handles index loading, tensor generation, text normalization, and
    the application of the additive heuristic scalpel matrix.
    """

    def __init__(self, model_path, index_dict, repos_dir=None, batch_size=64):
        print("\n[TRACE] --- Initializing MS2C Pipeline ---")
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        self.model = MS2CModel().to(self.device)

        if os.path.exists(model_path):
            self.model.load_state_dict(torch.load(model_path, map_location=self.device, weights_only=True))

        self.model.eval()
        self.text_tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base")
        self.image_processor = ViTImageProcessor.from_pretrained("google/vit-base-patch16-224-in21k")

        self.repos_dir = repos_dir
        self.unique_files = []
        self.file_embeddings = None
        self.global_corpus = []
        self.global_embeddings = None

        self._flatten_and_encode(index_dict, batch_size)

    @staticmethod
    def enrich_semantics(text, filepath="", is_query=False):
        """Injects contextual file boundaries into the raw AST text for CodeBERT to parse."""
        return text if is_query or not filepath else f"{text} | [Context: {os.path.basename(filepath).split('.')[0]}]"

    def _read_raw_file_content(self, relative_filepath):
        """Scans the physical repository to build the Stage 1 file-level document embeddings."""
        if not self.repos_dir: return f"File: {relative_filepath}"
        try:
            for repo_folder in os.listdir(self.repos_dir):
                potential_path = os.path.join(self.repos_dir, repo_folder, relative_filepath)
                if os.path.exists(potential_path):
                    with open(potential_path, 'r', encoding='utf-8') as f:
                        return f"File: {relative_filepath} Code: {re.sub(r'import .*? from .*?;', '', f.read())[:2000]}"
        except Exception:
            pass
        return f"File: {relative_filepath}"

    def _flatten_and_encode(self, index_dict, batch_size):
        """Pre-computes the semantic vector space for both files and individual nodes."""
        self.unique_files = list(index_dict.keys())
        file_texts = [self._read_raw_file_content(f) for f in self.unique_files]
        file_embs = []

        with torch.no_grad():
            for i in range(0, len(file_texts), batch_size):
                f_inputs = self.text_tokenizer(file_texts[i:i + batch_size], return_tensors="pt", truncation=True,
                                               padding="max_length", max_length=512).to(self.device)
                file_embs.append(self.model.forward_text(f_inputs["input_ids"], f_inputs["attention_mask"]).cpu())
        if file_embs: self.file_embeddings = torch.cat(file_embs, dim=0).to(self.device)

        self.global_corpus = [(key, node) for key, nodes in index_dict.items() for node in nodes]

        all_embeddings = []
        with torch.no_grad():
            for i in range(0, len(self.global_corpus), batch_size):
                b_texts = [self.enrich_semantics(item[1], filepath=item[0]) for item in
                           self.global_corpus[i: i + batch_size]]
                inputs = self.text_tokenizer(b_texts, return_tensors="pt", truncation=True, padding="max_length",
                                             max_length=128).to(self.device)
                all_embeddings.append(self.model.forward_text(inputs["input_ids"], inputs["attention_mask"]).cpu())
        if all_embeddings: self.global_embeddings = torch.cat(all_embeddings, dim=0).to(self.device)

    def retrieve_top_k(self, text_query, target_key=None, image_path=None, k=10, mode="multimodal", scope="component"):
        """
        Executes the 4-Stage Cascading Pipeline:
        1. NLP Token Generation
        2. Document Filtration (File Match)
        3. Multimodal Fused Scoring (CodeBERT + ViT)
        4. Additive Heuristic Matrix Application
        """
        print(f"\n[MS2C] retrieve_top_k called:")
        print(f"  corpus_size: {len(self.global_corpus)}")
        print(f"  embeddings_available: {self.global_embeddings is not None}")
        print(f"  query: {text_query[:50]}...")
        print(f"  scope: {scope}")
        
        if self.global_embeddings is None or len(self.global_corpus) == 0:
            print(f"  ❌ EARLY RETURN: No embeddings or corpus!")
            return [], 0.0

        q_lower = text_query.lower()
        invalid_markers = ["<svg", "<path", "<g ", "<circle", "<rect", "<line", "<polygon"]

        with torch.no_grad():
            text_inputs = self.text_tokenizer(q_lower, return_tensors="pt", truncation=True, padding="max_length",
                                              max_length=128).to(self.device)
            text_emb = self.model.forward_text(text_inputs["input_ids"], text_inputs["attention_mask"])

            # --- STAGE 1: NLP TOKENS ---
            STOPWORDS = {"the", "are", "was", "were", "been", "being", "for", "with", "from", "into", "after", "then",
                         "once", "here", "there", "when", "where", "why", "how", "both", "each", "few", "such", "nor",
                         "not", "only", "own", "than", "too", "very", "can", "will", "just", "now", "its", "they",
                         "them", "their", "this", "that", "these", "those", "our", "you", "your", "yours", "him", "his",
                         "she", "her", "hers", "and", "but", "while", "until", "does", "did", "doing", "has", "have",
                         "had"}

            query_words_set = set()
            for word in set(re.findall(r'\b[a-z0-9\-]+\b', q_lower)):
                if len(word) > 2 and word not in STOPWORDS:
                    query_words_set.add(word)
                    if len(word) > 4 and word.endswith('ies'):
                        query_words_set.update([word[:-3], word[:-3] + 'y'])
                    elif len(word) > 3 and word.endswith('es') and not word.endswith('ses'):
                        query_words_set.update([word[:-1], word[:-2]])
                    elif len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
                        query_words_set.add(word[:-1])
                    elif len(word) > 3 and word.endswith('y'):
                        query_words_set.update([word[:-1], word[:-1] + 'ies'])

            print(f"\n  [STAGE 1] Query tokens: {query_words_set}")

            # --- STAGE 2: DOCUMENT FILTRATION ---
            exact_match_files, partial_match_files = set(), set()

            if scope == "component":
                print(f"  [STAGE 2] COMPONENT SCOPE - Looking for target_key: {target_key}")
                if not target_key:
                    print(f"  ❌ No target_key provided for component scope. Returning empty.")
                    return [], 0.0
                valid_indices = [i for i, item in enumerate(self.global_corpus) if
                                 item[0] == target_key and not any(m in item[1].lower() for m in invalid_markers)]
            else:
                print(f"  [STAGE 2] REPOSITORY SCOPE - Filtering documents...")
                file_sim = torch.matmul(text_emb, self.file_embeddings.T).squeeze(0)
                for idx, filepath in enumerate(self.unique_files):
                    filename = os.path.basename(filepath).split('.')[0].lower()
                    if filename in query_words_set:
                        file_sim[idx] += 2.0
                        exact_match_files.add(filepath)
                    elif any(len(w) >= 3 and w in filename for w in query_words_set):
                        file_sim[idx] += 1.0
                        partial_match_files.add(filepath)

                top_files = [self.unique_files[i] for i in
                             torch.topk(file_sim, min(5, len(self.unique_files))).indices.tolist()]
                print(f"  [STAGE 2] Top files selected: {len(top_files)}")
                valid_indices = [i for i, item in enumerate(self.global_corpus) if
                                 item[0] in top_files and not any(m in item[1].lower() for m in invalid_markers)]
                print(f"  [STAGE 2] Valid indices after filtering: {len(valid_indices)}")

            if not valid_indices:
                print(f"  ❌ [STAGE 2] No valid indices! Returning empty.")
                return [], 0.0

            # Extract Tags
            available_tags = {tag.group(1) for idx in valid_indices if
                              (tag := re.search(r'<\s*([a-z0-9\-.]+)', self.global_corpus[idx][1].lower()))}
            exact_target_tags = {tag for tag in available_tags for word in query_words_set if
                                 tag == word or (word == "link" and tag == "a") or (
                                             word in ["image", "picture"] and tag == "img")}
            partial_target_tags = {tag for tag in available_tags for word in query_words_set if
                                   len(word) >= 3 and word in tag}

            # --- STAGE 3: MULTIMODAL GATING ---
            text_sim = torch.matmul(text_emb, self.global_embeddings.T).squeeze(0)

            if mode == "unimodal" or not image_path:
                final_scores, alpha_val = text_sim, 1.0
            else:
                img_inputs = self.image_processor(images=Image.open(image_path).convert("RGB"), return_tensors="pt").to(
                    self.device)
                vis_sim = torch.matmul(self.model.forward_image(img_inputs["pixel_values"]),
                                       self.global_embeddings.T).squeeze(0)
                base_alpha = self.model.compute_gating_weight(text_emb, self.model.forward_image(
                    img_inputs["pixel_values"])).squeeze()

                # Dynamic Gating with 0.70 Vectorized Floor Clamp
                alpha_vector = torch.where(text_sim > 0.80, torch.tensor(0.95, device=self.device),
                                           torch.clamp(base_alpha + 0.20, min=0.70, max=0.95))
                alpha_val = alpha_vector.mean().item()
                final_scores = (alpha_vector * text_sim) + ((1.0 - alpha_vector) * vis_sim)

            filtered_scores = final_scores.squeeze()[valid_indices].clone() if final_scores.dim() > 1 else final_scores[
                valid_indices].clone()

            # --- STAGE 4: HEURISTIC MATRIX BOOSTING ---
            boost_tensor = torch.zeros_like(filtered_scores)

            for i, idx in enumerate(valid_indices):
                node_file, node_str = self.global_corpus[idx][0], self.global_corpus[idx][1].lower()

                # Tier 0: File Override
                boost_tensor[
                    i] += 10.0 if node_file in exact_match_files else 5.0 if node_file in partial_match_files else 0.0

                # Tier 1: Tag Match
                if tag_match := re.search(r'<\s*([a-z0-9\-.]+)', node_str):
                    tag = tag_match.group(1)
                    boost_tensor[i] += 1.0 if tag in exact_target_tags else 0.5 if tag in partial_target_tags else 0.0

                # Tier 2: CSS Match
                if class_match := re.search(r'classname=["\']([^"\']+)["\']', node_str):
                    classes_list, class_str = class_match.group(1).split(), class_match.group(1)
                    for word in query_words_set:
                        if len(word) >= 3:
                            if word in classes_list:
                                boost_tensor[i] += 0.5; break
                            elif word in class_str:
                                boost_tensor[i] += 0.25; break

                # Tier 3: Deep Attribute Match
                for word in query_words_set:
                    if len(word) >= 3 and word in node_str and not (tag_match and word == tag_match.group(1)):
                        boost_tensor[i] += 0.25
                        break

            filtered_scores += boost_tensor

            # Determine Top-K
            top_k_indices = [valid_indices[idx] for idx in
                             torch.topk(filtered_scores, min(k, len(valid_indices))).indices.tolist()]
            raw_results = [self.global_corpus[i] for i in top_k_indices]

            return [item[1] for item in raw_results] if scope == "component" else raw_results, alpha_val