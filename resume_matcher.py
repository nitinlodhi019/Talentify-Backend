# resume_matcher.py
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import re
from sentence_transformers import SentenceTransformer

try:
    model = SentenceTransformer('all-MiniLM-L6-v2')
except Exception as e:
    print(f"Could not load SentenceTransformer model: {e}. Semantic similarity will fall back to TF-IDF.")
    model = None

def calculate_match_score_enhanced(job_description_text, required_skills, experience_required,
                                   resume_processed_text, resume_extracted_skills, hf_api_key=None):

    WEIGHT_SEMANTIC = 0.15  #
    WEIGHT_SKILL_MATCH = 0.75
    WEIGHT_EXPERIENCE = 0.10

    semantic_similarity = 0.0
    if model:
        try:
            embeddings = model.encode([job_description_text, resume_processed_text])
            semantic_similarity = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
        except Exception as e:
            print(f"Error with SentenceTransformer embeddings: {e}. Falling back to TF-IDF.")
            documents = [job_description_text, resume_processed_text]
            tfidf_vectorizer = TfidfVectorizer()
            tfidf_matrix = tfidf_vectorizer.fit_transform(documents)
            semantic_similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
    else:
        documents = [job_description_text, resume_processed_text]
        tfidf_vectorizer = TfidfVectorizer()
        tfidf_matrix = tfidf_vectorizer.fit_transform(documents)
        semantic_similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

    # Normalize to 0–1
    semantic_similarity = (semantic_similarity + 1) / 2

    # Skill Matching (Case-insensitive, partial match allowed)
    resume_skills_lower = [es.lower() for es in resume_extracted_skills]
    required_skills_lower = [skill.lower() for skill in required_skills]

    matched_required_skills = [
        skill for skill in required_skills_lower
        if any(skill in rs or rs in skill for rs in resume_skills_lower)
    ]

    skill_match_percentage = 0
    if required_skills_lower:
        skill_match_percentage = len(matched_required_skills) / len(required_skills_lower)

    # Strong boost for high skill match, softer penalty for low match
    if skill_match_percentage > 0.7:
        skill_match_percentage *= 1.2  # 20% boost
    elif skill_match_percentage < 0.3:
        skill_match_percentage *= 0.85  # Slight penalty

    # Experience Matching
    experience_score = 0.0
    if experience_required and experience_required != "Any":
        job_min_exp, job_max_exp = 0, float('inf')
        if '-' in experience_required:
            parts = experience_required.split('-')
            job_min_exp = int(parts[0])
            job_max_exp = int(parts[1].replace('+', '')) if '+' in parts[1] else int(parts[1])
        elif '+' in experience_required:
            job_min_exp = int(experience_required.replace('+', ''))

        resume_experience_match = re.search(
            r'(\d+)(?:\s*-\s*(\d+))?\+?\s*(?:year|yr)s?(?:\s*of)?\s*experience',
            resume_processed_text, re.IGNORECASE
        )
        if resume_experience_match:
            resume_min_years = int(resume_experience_match.group(1))
            resume_max_years = int(resume_experience_match.group(2)) if resume_experience_match.group(2) else resume_min_years

            if (job_min_exp <= resume_max_years and job_max_exp >= resume_min_years):
                experience_score = 1.0
            elif resume_min_years > job_max_exp:
                experience_score = 0.8
            elif resume_max_years < job_min_exp:
                experience_score = 0.4
            else:
                experience_score = 0.6
        else:
            job_desc_lower = job_description_text.lower()
            resume_text_lower = resume_processed_text.lower()
            if "senior" in job_desc_lower and "senior" in resume_text_lower:
                experience_score = 0.9
            elif "junior" in job_desc_lower and "junior" in resume_text_lower:
                experience_score = 0.9
            elif "entry-level" in job_desc_lower and "entry-level" in resume_text_lower:
                experience_score = 0.9
            elif "lead" in job_desc_lower and "lead" in resume_text_lower:
                experience_score = 0.85
            elif "manager" in job_desc_lower and "manager" in resume_text_lower:
                experience_score = 0.8
            else:
                experience_score = 0.6

    # Combine Scores
    total_weight = WEIGHT_SEMANTIC + WEIGHT_SKILL_MATCH + WEIGHT_EXPERIENCE
    final_score = (
        (semantic_similarity * WEIGHT_SEMANTIC) +
        (skill_match_percentage * WEIGHT_SKILL_MATCH) +
        (experience_score * WEIGHT_EXPERIENCE)
    )
    final_score = (final_score / total_weight) * 100

    # Ensure within 0–100
    final_score = np.clip(final_score, 0, 100)

    return final_score, matched_required_skills

