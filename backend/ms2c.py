# ms2c.py
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
1. Document Filter: Multi-tiered file routing (Directional Substring).
2. Entity Extraction: Dynamic Tag Parsing (Safe word-in-tag matching).
3. Semantic Scorer: CodeBERT + ViT ranking using Context Injection, applying a 
   tiered Dynamic Soft Boost for File Overrides, Tags, ClassNames, and Deep Attributes.
=========================================================================================
"""


class MS2CModel(nn.Module):
    def __init__(self, hidden_dim=768):
        super(MS2CModel, self).__init__()
        self.codebert = AutoModel.from_pretrained("microsoft/codebert-base")
        self.vit = ViTModel.from_pretrained("google/vit-base-patch16-224-in21k")
        self.mlp_projection = nn.Sequential(
            nn.Linear(self.vit.config.hidden_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim)
        )
        self.gating_network = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid()
        )

    def forward_text(self, input_ids, attention_mask):
        outputs = self.codebert(input_ids=input_ids, attention_mask=attention_mask)
        cls_embedding = outputs.last_hidden_state[:, 0, :]
        return torch.nn.functional.normalize(cls_embedding, p=2, dim=1)

    def forward_image(self, pixel_values):
        outputs = self.vit(pixel_values=pixel_values)
        cls_embedding = outputs.last_hidden_state[:, 0, :]
        projected_embedding = self.mlp_projection(cls_embedding)
        return torch.nn.functional.normalize(projected_embedding, p=2, dim=1)

    def compute_gating_weight(self, text_emb, visual_emb):
        fused_features = torch.cat([text_emb, visual_emb], dim=1)
        return self.gating_network(fused_features)


class MS2CRetriever:
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

    def enrich_semantics(self, text, filepath="", is_query=False):
        if is_query or not filepath:
            return text

        # Inject File Context to help CodeBERT identify component boundaries
        comp_name = os.path.basename(filepath).split('.')[0]
        return f"{text} | [Context: {comp_name}]"

    def _read_raw_file_content(self, relative_filepath):
        if not self.repos_dir: return f"File: {relative_filepath}"
        try:
            for repo_folder in os.listdir(self.repos_dir):
                potential_path = os.path.join(self.repos_dir, repo_folder, relative_filepath)
                if os.path.exists(potential_path):
                    with open(potential_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        return f"File: {relative_filepath} Code: {re.sub(r'import .*? from .*?;', '', content)[:2000]}"
            return f"File: {relative_filepath}"
        except Exception:
            return f"File: {relative_filepath}"

    def _flatten_and_encode(self, index_dict, batch_size):
        self.unique_files = list(index_dict.keys())
        file_texts = [self._read_raw_file_content(f) for f in self.unique_files]
        file_embs = []

        with torch.no_grad():
            for i in range(0, len(file_texts), batch_size):
                b_files = file_texts[i:i + batch_size]
                f_inputs = self.text_tokenizer(b_files, return_tensors="pt", truncation=True, padding="max_length",
                                               max_length=512).to(self.device)
                file_embs.append(self.model.forward_text(f_inputs["input_ids"], f_inputs["attention_mask"]).cpu())
        if file_embs: self.file_embeddings = torch.cat(file_embs, dim=0).to(self.device)

        for key, nodes in index_dict.items():
            for node in nodes: self.global_corpus.append((key, node))

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
        if self.global_embeddings is None or len(self.global_corpus) == 0: return [], 0.0

        q_lower = text_query.lower()

        with torch.no_grad():
            text_inputs = self.text_tokenizer(q_lower, return_tensors="pt", truncation=True, padding="max_length",
                                              max_length=128).to(self.device)
            text_emb = self.model.forward_text(text_inputs["input_ids"], text_inputs["attention_mask"])

            invalid_markers = ["<svg", "<path", "<g ", "<circle", "<rect", "<line", "<polygon"]

            # ==============================================================================
            # THE NOISE FILTER & TRIPLE-VARIANT PLURALIZATION
            # ==============================================================================
            STOPWORDS = {
                "the", "are", "was", "were", "been", "being", "for", "with", "from",
                "into", "after", "then", "once", "here", "there", "when", "where",
                "why", "how", "both", "each", "few", "such", "nor", "not", "only",
                "own", "than", "too", "very", "can", "will", "just", "now", "its",
                "they", "them", "their", "this", "that", "these", "those", "our",
                "you", "your", "yours", "him", "his", "she", "her", "hers", "and",
                "but", "while", "until", "does", "did", "doing", "has", "have", "had"
            }

            raw_query_words = set(re.findall(r'\b[a-z0-9\-]+\b', q_lower))
            query_words_set = set()

            for word in raw_query_words:
                if len(word) <= 2 or word in STOPWORDS:
                    continue

                # Variant 1: Original
                query_words_set.add(word)

                # Variants 2 & 3: Cut and Singular/Plural
                if len(word) > 4 and word.endswith('ies'):
                    query_words_set.add(word[:-3])  # categor
                    query_words_set.add(word[:-3] + 'y')  # category
                elif len(word) > 3 and word.endswith('es') and not word.endswith('ses'):
                    query_words_set.add(word[:-1])  # boxe (rare but helpful)
                    query_words_set.add(word[:-2])  # box
                elif len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
                    query_words_set.add(word[:-1])  # button
                elif len(word) > 3 and word.endswith('y'):
                    query_words_set.add(word[:-1])  # amenit
                    query_words_set.add(word[:-1] + 'ies')  # amenities

            exact_match_files = set()
            partial_match_files = set()

            # ==============================================================================
            # PIPELINE STAGE 1: Document Filter (Multi-Tier File Name Routing)
            # ==============================================================================
            if scope == "component":
                if not target_key: return [], 0.0
                valid_indices = [i for i, item in enumerate(self.global_corpus) if
                                 item[0] == target_key and "className" in item[1] and not any(
                                     m in item[1].lower() for m in invalid_markers)]
            else:
                file_sim = torch.matmul(text_emb, self.file_embeddings.T).squeeze(0)

                for idx, filepath in enumerate(self.unique_files):
                    filename = os.path.basename(filepath).split('.')[0].lower()

                    is_exact = False
                    for word in query_words_set:
                        if filename == word:
                            file_sim[idx] += 2.0
                            exact_match_files.add(filepath)
                            is_exact = True
                            break

                    if not is_exact:
                        for word in query_words_set:
                            if len(word) >= 3 and word in filename:
                                file_sim[idx] += 1.0
                                partial_match_files.add(filepath)
                                break

                top_files = [self.unique_files[idx] for idx in
                             torch.topk(file_sim, min(5, len(self.unique_files))).indices.tolist()]
                valid_indices = [i for i, item in enumerate(self.global_corpus) if
                                 item[0] in top_files and "className" in item[1] and not any(
                                     m in item[1].lower() for m in invalid_markers)]

            if not valid_indices: return [], 0.0

            # ==============================================================================
            # PIPELINE STAGE 2: Entity Extraction (Dynamic Parsing & Intersection)
            # ==============================================================================
            available_tags = set()
            for idx in valid_indices:
                node_str = self.global_corpus[idx][1].lower()
                tag_match = re.search(r'<\s*([a-z0-9\-]+)', node_str)
                if tag_match:
                    available_tags.add(tag_match.group(1))

            exact_target_tags = set()
            partial_target_tags = set()

            for tag in available_tags:
                for word in query_words_set:
                    if tag == word:
                        exact_target_tags.add(tag)
                    elif word == "link" and tag == "a":
                        exact_target_tags.add(tag)
                    elif (word == "image" or word == "picture") and tag == "img":
                        exact_target_tags.add(tag)
                    elif len(word) >= 3 and word in tag:
                        partial_target_tags.add(tag)

            # ==============================================================================
            # PIPELINE STAGE 3: Semantic Scorer & Multi-Tier Tensor Boost
            # ==============================================================================
            text_sim = torch.matmul(text_emb, self.global_embeddings.T).squeeze(0)

            if mode == "unimodal" or image_path is None:
                final_scores = text_sim
                alpha_val = 1.0
            else:
                image = Image.open(image_path).convert("RGB")
                img_inputs = self.image_processor(images=image, return_tensors="pt").to(self.device)
                vis_sim = torch.matmul(self.model.forward_image(img_inputs["pixel_values"]),
                                       self.global_embeddings.T).squeeze(0)

                base_alpha = self.model.compute_gating_weight(text_emb, self.model.forward_image(
                    img_inputs["pixel_values"])).squeeze()
                alpha_vector = torch.where(text_sim > 0.80, torch.tensor(0.95, device=self.device),
                                           torch.clamp(base_alpha + 0.20, min=0.70, max=0.95))
                alpha_val = alpha_vector.mean().item()

                final_scores = (alpha_vector * text_sim) + ((1.0 - alpha_vector) * vis_sim)

            if final_scores.dim() > 1: final_scores = final_scores.squeeze()

            filtered_scores = final_scores[valid_indices].clone()

            # --- DYNAMIC TIERED TENSOR BOOSTING ---
            boost_tensor = torch.zeros_like(filtered_scores)

            for i, idx in enumerate(valid_indices):
                node_file = self.global_corpus[idx][0]
                node_str = self.global_corpus[idx][1].lower()

                # Priority 0: The File Override Boost
                if node_file in exact_match_files:
                    boost_tensor[i] += 10.0
                elif node_file in partial_match_files:
                    boost_tensor[i] += 5.0

                # Priority 1: HTML/React Tag Match
                tag_match = re.search(r'<\s*([a-z0-9\-]+)', node_str)
                if tag_match:
                    tag = tag_match.group(1)
                    if tag in exact_target_tags:
                        boost_tensor[i] += 1.0
                    elif tag in partial_target_tags:
                        boost_tensor[i] += 0.5

                # Priority 2: CSS ClassName Match
                class_match = re.search(r'classname=["\']([^"\']+)["\']', node_str)
                if class_match:
                    classes_list = class_match.group(1).split()
                    class_str = class_match.group(1)

                    for word in query_words_set:
                        if len(word) >= 3:
                            if word in classes_list:
                                boost_tensor[i] += 0.5
                                break
                            elif word in class_str:
                                boost_tensor[i] += 0.25
                                break

                # Priority 3: Deep Attribute Match
                for word in query_words_set:
                    if len(word) >= 3 and word in node_str:
                        if not (tag_match and word == tag_match.group(1)):
                            boost_tensor[i] += 0.25
                            break

            filtered_scores += boost_tensor
            # --------------------------------------

            top_k_val = min(k, len(valid_indices))
            top_k_indices = [valid_indices[idx] for idx in
                             torch.topk(filtered_scores, top_k_val).indices.tolist()]

            raw_results = [self.global_corpus[i] for i in top_k_indices]
            return [item[1] for item in raw_results] if scope == "component" else raw_results, alpha_val