# News Enhancement

Planned enhancements:

1. Naver News Search API integration
- Use NAVER_CLIENT_ID and NAVER_CLIENT_SECRET environment variables
- Search by registered keywords
- Merge with RSS results
- Remove duplicates by title/link
- Display source type (RSS/Search)

2. Automatic business memo generation
- AI -> 'AI 기술·정책 변화 확인 필요'
- ERP -> 'ERP 시장 및 경쟁사 동향 검토 필요'
- Cloud -> '클라우드/SaaS 사업 영향 검토 필요'
- Privacy -> '개인정보보호 정책 반영 여부 검토 필요'
- Policy -> '제도 변경 영향 검토 필요'

3. Auto importance scoring
- High: policy, regulation, security, 개인정보
- Medium: ERP, cloud
- Low: general trends

4. News UI improvements
- Show collection source
- Show auto-generated memo
- Allow manual override before save
