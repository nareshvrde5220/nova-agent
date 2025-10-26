import os
import json
import boto3
from datetime import datetime
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT

aws_region = os.getenv("AWS_REGION", "us-east-1")
model_id = "amazon.nova-pro-v1:0"

s3_client = boto3.client('s3', region_name=aws_region)
bedrock_client = boto3.client('bedrock-runtime', region_name=aws_region)

S3_BUCKET = 'trianz-aws-hackathon'


def extract_policy_data_from_summary(final_summary: str) -> dict:
    """Extract structured policy data from HTML summary using Nova Pro"""
    
    prompt = f"""
You are an AI that outputs ONLY valid JSON. Extract US Health Insurance Policy data from the underwriting summary.

Required JSON structure:
{{
  "title": "HEALTH INSURANCE POLICY",
  "policy_details": [
    {{"field": "POLICYHOLDER NAME:", "value": ""}},
    {{"field": "POLICY NUMBER:", "value": ""}},
    {{"field": "POLICY EFFECTIVE DATE:", "value": ""}},
    {{"field": "POLICY TERMINATION DATE:", "value": ""}},
    {{"field": "POLICY TYPE:", "value": ""}},
    {{"field": "COVERAGE AMOUNT:", "value": ""}},
    {{"field": "ANNUAL PREMIUM:", "value": ""}},
    {{"field": "STATE OF ISSUANCE:", "value": "USA"}},
    {{"field": "UNDERWRITING DECISION:", "value": ""}}
  ],
  "description": "This Policy describes the terms and conditions of Health insurance coverage based on comprehensive underwriting analysis. Coverage is subject to all terms, conditions, and exclusions outlined herein.",
  "coverage_details": [
    {{"class": "PRIMARY COVERAGE", "benefit_name": "Life Insurance Coverage", "details": [
      {{"label": "Death Benefit", "value": ""}},
      {{"label": "Policy Term", "value": ""}},
      {{"label": "Premium Payment Frequency", "value": "Monthly"}}
    ]}},
    {{"class": "MEDICAL COVERAGE", "benefit_name": "Health Benefits", "details": [
      {{"label": "Medical Risk Classification", "value": ""}},
      {{"label": "Health Status", "value": ""}}
    ]}},
    {{"class": "EXCLUSIONS", "benefit_name": "Policy Exclusions", "details": [
      {{"label": "Pre-existing Conditions", "value": "As per underwriting"}},
      {{"label": "High-Risk Activities", "value": "As per underwriting"}}
    ]}}
  ],
  "underwriting_summary": {{
    "medical_status": "",
    "financial_status": "",
    "driving_status": "",
    "compliance_status": "",
    "final_decision": "",
    "conditions": ""
  }}
}}

EXTRACTION RULES:
- Extract actual values from the summary
- Use "Not Specified" if data not found
- Preserve all currency values as-is (e.g., $500,000 USD)
- Extract coverage amount, premium, policy type
- Extract applicant name if mentioned
- Extract medical, financial, driving risk classifications
- Extract final underwriting decision (Approved/Declined/Review)
- Generate policy number format: POL-USA-YYYYMMDD-XXXX where YYYYMMDD is today's date and XXXX is 4 random digits
- Policy effective date: Today's date
- Policy termination date: Effective date + policy term (extract from summary)

Underwriting Summary Data:
{final_summary}
"""

    try:
        response = bedrock_client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 4000, "temperature": 0.0}
        )

        json_text = response["output"]["message"]["content"][0]["text"].strip()
        
        # Clean markdown if present
        if json_text.startswith("```"):
            json_text = json_text.strip("```")
            if json_text.lower().startswith("json"):
                json_text = json_text[4:].strip()

        policy_data = json.loads(json_text)
        print(f"[POLICY] Successfully extracted policy data from summary")
        return policy_data
        
    except Exception as e:
        print(f"[ERROR] Failed to extract policy data: {e}")
        return None


def create_table_border(cell):
    """Add borders to table cell"""
    tcPr = cell._element.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4')
        border.set(qn('w:color'), '000000')
        tcBorders.append(border)
    tcPr.append(tcBorders)


def generate_policy_pdf_document(policy_data: dict, output_file: str) -> bool:
    """Generate formatted PDF policy document"""
    
    try:
        doc = SimpleDocTemplate(output_file, pagesize=letter,
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=18)
        
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#003366'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#003366'),
            spaceAfter=12,
            fontName='Helvetica-Bold'
        )
        
        # TITLE
        title = Paragraph(policy_data.get('title', 'HEALTH INSURANCE POLICY'), title_style)
        story.append(title)
        story.append(Spacer(1, 0.3*inch))
        
        # POLICY DETAILS TABLE
        story.append(Paragraph('POLICY INFORMATION', heading_style))
        story.append(Spacer(1, 0.1*inch))
        
        details = policy_data.get('policy_details', [])
        details_data = [[item['field'], item['value']] for item in details]
        
        details_table = Table(details_data, colWidths=[2.5*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F0F8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(details_table)
        story.append(Spacer(1, 0.3*inch))
        
        # DESCRIPTION
        desc = Paragraph(policy_data.get('description', ''), styles['Normal'])
        story.append(desc)
        story.append(Spacer(1, 0.3*inch))
        
        # COVERAGE DETAILS
        story.append(Paragraph('COVERAGE DETAILS & BENEFITS', heading_style))
        story.append(Spacer(1, 0.1*inch))
        
        coverage_details = policy_data.get('coverage_details', [])
        
        for coverage in coverage_details:
            coverage_class = coverage.get('class', '')
            benefit_name = coverage.get('benefit_name', '')
            
            # Coverage class header
            class_heading = Paragraph(
                f"<b>{coverage_class}: {benefit_name}</b>",
                ParagraphStyle('CoverageClass', parent=styles['Normal'],
                              fontSize=12, textColor=colors.HexColor('#004F9E'),
                              fontName='Helvetica-Bold', spaceAfter=6)
            )
            story.append(class_heading)
            
            # Details table
            details_list = coverage.get('details', [])
            if details_list:
                coverage_data = []
                for detail in details_list:
                    label = detail.get('label', '')
                    value = detail.get('value', '')
                    min_perc = detail.get('min_perc', '')
                    max_perc = detail.get('max_perc', '')
                    
                    if min_perc and max_perc:
                        display_value = f"{min_perc} - {max_perc} {value}"
                    else:
                        display_value = value
                    
                    coverage_data.append([label, display_value])
                
                coverage_table = Table(coverage_data, colWidths=[2.5*inch, 4*inch])
                coverage_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F0F8FF')),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey)
                ]))
                story.append(coverage_table)
            
            story.append(Spacer(1, 0.2*inch))
        
        # UNDERWRITING SUMMARY
        story.append(Paragraph('UNDERWRITING SUMMARY', heading_style))
        story.append(Spacer(1, 0.1*inch))
        
        underwriting_data = policy_data.get('underwriting_summary', {})
        
        underwriting_items = [
            ['Medical Status', underwriting_data.get('medical_status', 'N/A')],
            ['Financial Status', underwriting_data.get('financial_status', 'N/A')],
            ['Driving Record Status', underwriting_data.get('driving_status', 'N/A')],
            ['Compliance Status', underwriting_data.get('compliance_status', 'N/A')],
            ['Final Decision', underwriting_data.get('final_decision', 'N/A')],
            ['Special Conditions', underwriting_data.get('conditions', 'None')]
        ]
        
        uw_table = Table(underwriting_items, colWidths=[2.5*inch, 4*inch])
        uw_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F0F8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(uw_table)
        story.append(Spacer(1, 0.3*inch))
        
        # FOOTER
        footer_text = (
            f"Document Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br/>"
            "This is a computer-generated policy document based on automated underwriting analysis.<br/>"
            "Policy is subject to final review and approval by authorized underwriting personnel."
        )
        footer = Paragraph(footer_text, 
                          ParagraphStyle('Footer', parent=styles['Normal'],
                                        fontSize=9, textColor=colors.grey,
                                        alignment=TA_CENTER))
        story.append(footer)
        
        # Build PDF
        doc.build(story)
        print(f"[POLICY] PDF document generated: {output_file}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to generate PDF document: {e}")
        import traceback
        traceback.print_exc()
        return False

def generate_health_insurance_policy(session_id: str) -> dict:
    """Main function to generate health insurance policy from S3 agent_status.json"""
    
    try:
        print(f"[POLICY] Starting policy generation for session: {session_id}")
        
        # Step 1: Read agent_status.json from S3
        s3_key = f"{session_id}/agent_status.json"
        
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
            agent_status = json.loads(response['Body'].read().decode('utf-8'))
            print(f"[POLICY] Successfully read agent_status.json from S3")
        except Exception as e:
            print(f"[ERROR] Failed to read agent_status.json: {e}")
            return {
                'status': 'error',
                'error': f'Could not read agent_status.json: {str(e)}',
                'session_id': session_id
            }
        
        # Step 2: Check if underwriting is completed successfully
        overall_status = agent_status.get('status', '')
        if overall_status != 'completed':
            print(f"[POLICY] Underwriting not completed. Status: {overall_status}")
            return {
                'status': 'skipped',
                'message': 'Underwriting not completed yet',
                'session_id': session_id
            }
        
        # Step 3: Extract final_summary
        final_summary = agent_status.get('final_summary', '')
        
        if not final_summary or len(final_summary) < 100:
            print(f"[ERROR] No valid final_summary found")
            return {
                'status': 'error',
                'error': 'No final summary available',
                'session_id': session_id
            }
        
        # Step 4: Check if documents verified (simple check in summary text)
        summary_lower = final_summary.lower()
        if 'decline' in summary_lower or 'denied' in summary_lower or 'failed' in summary_lower:
            print(f"[POLICY] Underwriting declined - skipping policy generation")
            return {
                'status': 'declined',
                'message': 'Underwriting declined - policy not generated',
                'session_id': session_id
            }
        
        print(f"[POLICY] Final summary length: {len(final_summary)} characters")
        
        # Step 5: Extract structured policy data using Nova Pro
        policy_data = extract_policy_data_from_summary(final_summary)
        
        if not policy_data:
            return {
                'status': 'error',
                'error': 'Failed to extract policy data',
                'session_id': session_id
            }
        
        # Step 6: Generate Word document
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_filename = f"policy_generated_{session_id}_{timestamp}.pdf"
        
        success = generate_policy_pdf_document(policy_data, local_filename)
        
        if not success:
            return {
                'status': 'error',
                'error': 'Failed to generate Word document',
                'session_id': session_id
            }
        
        # Step 7: Upload to S3
        s3_policy_key = f"{session_id}/policy_generated_{timestamp}.pdf"
        
        try:
            with open(local_filename, 'rb') as f:
                s3_client.upload_fileobj(
                    f,
                    S3_BUCKET,
                    s3_policy_key,
                    ExtraArgs={
                        'ContentType': 'application/pdf',
                        'ContentDisposition': 'inline',
                        'Metadata': {
                            'session_id': session_id,
                            'generated_at': datetime.now().isoformat(),
                            'document_type': 'health_insurance_policy'
                        }
                    }
                )
            print(f"[POLICY] Uploaded to S3: s3://{S3_BUCKET}/{s3_policy_key}")
        except Exception as e:
            print(f"[ERROR] Failed to upload policy to S3: {e}")
            # Continue anyway - we have local file
        
        # Step 8: Update agent_status.json with policy info
        try:
            agent_status['policy_generated'] = {
                'status': 'completed',
                'timestamp': datetime.now().isoformat(),
                's3_location': f"s3://{S3_BUCKET}/{s3_policy_key}",
                'local_file': local_filename,
                'policy_number': next(
                    (item['value'] for item in policy_data.get('policy_details', []) 
                     if 'POLICY NUMBER' in item['field']), 
                    'N/A'
                )
            }
            
            # Save updated agent_status back to S3
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=json.dumps(agent_status, indent=2, ensure_ascii=False),
                ContentType='application/json'
            )
            print(f"[POLICY] Updated agent_status.json with policy info")
            
        except Exception as e:
            print(f"[WARNING] Failed to update agent_status.json: {e}")
        
        # Step 9: Return success response
        return {
            'status': 'success',
            'session_id': session_id,
            'policy_generated': True,
            's3_location': f"s3://{S3_BUCKET}/{s3_policy_key}",
            'local_file': local_filename,
            's3_key': s3_policy_key,
            'timestamp': timestamp,
            'message': 'Health insurance policy generated successfully'
        }
        
    except Exception as e:
        print(f"[ERROR] Policy generation failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'error': str(e),
            'session_id': session_id
        }


__all__ = ['generate_health_insurance_policy']