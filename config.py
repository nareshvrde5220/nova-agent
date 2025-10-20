import os

NOVA_PRO_MODEL_ID = "amazon.nova-pro-v1:0"

UNDERWRITING_GUIDELINES = {
    "age_limits": {
        "min_age": 18,
        "max_age": 75,
        "senior_threshold": 65
    },
    "coverage_limits": {
        "min_coverage": 50000,
        "max_coverage": 5000000,
        "standard_max": 1000000
    },
    "medical_requirements": {
        "age_50_plus": "Full medical exam required",
        "coverage_1M_plus": "Comprehensive health screening",
        "high_risk_occupations": "Additional medical clearance"
    },
    "financial_ratios": {
        "income_multiplier": 10,
        "debt_to_income_max": 0.4,
        "net_worth_min": 100000
    },
    "risk_categories": {
        "preferred_plus": {"multiplier": 0.8, "max_age": 55},
        "preferred": {"multiplier": 1.0, "max_age": 65},
        "standard": {"multiplier": 1.2, "max_age": 70},
        "substandard": {"multiplier": 1.5, "max_age": 75}
    }
}

REQUIRED_DOCUMENTS = {
    "application_form": "mandatory",
    "medical_records": {
        "required_if": "age_over_50_or_coverage_over_500K",
        "includes": ["physician_statement", "medical_exam", "lab_results"]
    },
    "driving_records": {
        "required_if": "coverage_over_1M",
        "lookback_years": 5
    },
    "financial_statements": {
        "required_if": "coverage_over_500K",
        "includes": ["tax_returns", "bank_statements", "investment_accounts"]
    },
    "identity_verification": "mandatory"
}

RISK_SCORING_RULES = {
    "mortality_factors": {
        "age_weight": 0.3,
        "health_weight": 0.4,
        "lifestyle_weight": 0.2,
        "financial_weight": 0.1
    },
    "health_risk_indicators": {
        "diabetes": 1.8,
        "heart_disease": 2.2,
        "cancer_history": 1.9,
        "smoking": 1.5,
        "obesity": 1.3
    },
    "lifestyle_risk_factors": {
        "dangerous_hobbies": 1.4,
        "excessive_drinking": 1.6,
        "poor_driving": 1.3,
        "high_stress_job": 1.2
    },
    "approval_thresholds": {
        "auto_approve": 0.8,
        "manual_review": 1.2,
        "decline": 1.8
    }
}

BUSINESS_RULES = {
    "auto_approval_criteria": {
        "age_range": (25, 55),
        "coverage_max": 1000000,
        "health_score_min": 0.8,
        "financial_score_min": 0.7
    },
    "manual_review_triggers": [
        "high_coverage_amount",
        "complex_medical_history",
        "financial_inconsistencies",
        "regulatory_flags"
    ],
    "decline_criteria": {
        "terminal_illness": True,
        "financial_fraud": True,
        "regulatory_violations": True,
        "age_limit_exceeded": True
    }
}

AGENT_WORKFLOW_SEQUENCE = [
    "data_intake",
    "document_verification", 
    "medical_risk_assessment",
    "financial",
    "driving",
    "compliance",
    "lifestyle_behavioral",
    "summary_generation"
]

LIFESTYLE_RISK_FACTORS = {
    # Substance Use
    "smoking_current": 2.0,
    "smoking_quit_recent": 1.3,
    "heavy_drinking": 1.8,
    "recreational_drug_use": 2.5,
    "prescription_drug_abuse": 2.2,
    
    # Travel & Geographic
    "frequent_international_travel": 1.2,
    "high_risk_country_residence": 1.5,
    "military_deployment_zones": 1.8,
    "remote_location_work": 1.3,
    
    # Mental Health & Behavioral
    "depression_history": 1.4,
    "anxiety_disorders": 1.2,
    "suicide_attempt_history": 3.5,
    "eating_disorders": 1.6,
    "gambling_addiction": 1.5,
    
    # Physical Health Behaviors
    "obesity_severe": 1.8,
    "sedentary_lifestyle": 1.3,
    "sleep_disorders": 1.2,
    "stress_related_conditions": 1.1,
    
    # Occupational Hazards
    "hazardous_occupation": 1.7,
    "law_enforcement": 1.4,
    "mining_construction": 1.6,
    "chemical_exposure_work": 1.5,
    
    # Financial Behavioral Patterns
    "bankruptcy_history": 1.3,
    "insurance_fraud_history": 4.0,
    "multiple_policy_applications": 1.4,
    "premium_payment_defaults": 1.2,
    
    # Social & Family Factors
    "family_suicide_history": 1.8,
    "family_addiction_history": 1.3,
    "domestic_violence_history": 1.6,
    "criminal_record": 1.9
}

LOCAL_CONFIG = {
    'UPLOAD_FOLDER': 'uploads',
    'SESSION_FOLDER': 'sessions',
    'ALLOWED_EXTENSIONS': {'.zip'},
    'MAX_FILE_SIZE': 50 * 1024 * 1024,
    'SESSION_TIMEOUT': 3600
}


TRIANZ_POLICY_TYPES = {
    'SILVER': {
        'name': 'Silver Policy - Foundation Protection',
        'description': 'Basic life insurance coverage for young professionals and singles',
        'coverage_range': {
            'min': 50000,
            'max': 500000
        },
        'premium_range': {
            'min_monthly': 25,
            'max_monthly': 75
        },
        'term_options': [10, 15, 20],
        'age_eligibility': {
            'min': 18,
            'max': 55
        },
        'features': [
            'Affordable monthly premiums starting from $25-$75',
            'Standard term options: 10, 15, or 20 years',
            'Basic death benefit protection for your beneficiaries',
            'No cash value accumulation (pure term insurance)',
            'Medical exam required for amounts over $250,000',
            'Ideal for covering debts, final expenses, or income replacement'
        ],
        'ideal_for': [
            'Young professionals aged 18-55',
            'Singles or young families',
            'Those seeking basic coverage',
            'Debt coverage needs',
            'Final expense planning',
            'Income replacement protection'
        ],
        'approval_timeline': '2-4 weeks',
        'underwriting_level': 'standard'
    },
    'GOLD': {
        'name': 'Gold Policy - Enhanced Protection',
        'description': 'Comprehensive coverage for families, homeowners, and established professionals',
        'coverage_range': {
            'min': 500000,
            'max': 2000000
        },
        'premium_range': {
            'min_monthly': 100,
            'max_monthly': 300
        },
        'term_options': [15, 20, 25, 30],
        'age_eligibility': {
            'min': 18,
            'max': 65
        },
        'features': [
            'Comprehensive coverage with enhanced benefits',
            'Term options: 15, 20, 25, or 30 years',
            'Optional riders available: disability waiver, accelerated death benefit',
            'Conversion option to permanent insurance',
            'Medical exam required for all applicants',
            'Living benefits: Access to policy value in case of critical illness',
            'Ideal for mortgage protection, college funding, comprehensive family security'
        ],
        'ideal_for': [
            'Families with dependents',
            'Homeowners with mortgages',
            'Established professionals',
            'Mortgage protection needs',
            'College education funding',
            'Comprehensive family security'
        ],
        'approval_timeline': '3-6 weeks',
        'underwriting_level': 'enhanced'
    },
    'PLATINUM': {
        'name': 'Platinum Policy - Premium Protection',
        'description': 'Maximum coverage for high-net-worth individuals, business owners, and estate planning',
        'coverage_range': {
            'min': 2000000,
            'max': 5000000
        },
        'premium_range': {
            'min_monthly': 400,
            'max_monthly': 1200
        },
        'term_options': [20, 25, 30, 'whole_life'],
        'age_eligibility': {
            'min': 18,
            'max': 75
        },
        'features': [
            'Maximum coverage with premium benefits',
            'Flexible term options: 20, 25, 30 years, or convertible whole life',
            'All optional riders included: disability, critical illness, long-term care',
            'Estate planning benefits and tax advantages',
            'Comprehensive medical underwriting required',
            'Priority claim processing for beneficiaries',
            'Optional investment component with cash value growth',
            'Business succession planning features',
            'Ideal for estate tax planning, business protection, wealth transfer, multi-generational security'
        ],
        'ideal_for': [
            'High-net-worth individuals',
            'Business owners and executives',
            'Estate planning needs',
            'Estate tax planning',
            'Business protection and succession',
            'Wealth transfer strategies',
            'Multi-generational security'
        ],
        'approval_timeline': '4-8 weeks',
        'underwriting_level': 'comprehensive'
    }
}


NOVA_SONIC_CONFIG = {
    'model_id': 'amazon.nova-sonic-v1:0',
    'region': 'us-east-1',
    'voice_id': 'matthew',  
    'voice_alternative': 'joanna',  
    'input_sample_rate': 16000,
    'output_sample_rate': 24000,
    'channels': 1,
    'sample_width': 2,
    'inference_config': {
        'maxTokens': 1024,
        'topP': 0.9,
        'temperature': 0.7
    }
}


TRIANZ_REQUIRED_DOCUMENTS = {
    'medical_records': {
        'name': 'Medical Records',
        'description': 'Recent physician statements or medical exam results from the past 12 months',
        'file_types': ['PDF', 'JPG', 'PNG'],
        'mandatory': True,
        'priority': 1
    },
    'driving_record': {
        'name': 'Driving Record (MVR)',
        'description': 'Motor Vehicle Report from your state DMV showing 5-year driving history',
        'file_types': ['PDF'],
        'mandatory': True,
        'priority': 2
    },
    'tax_returns': {
        'name': 'Tax Returns',
        'description': 'Last 2 years of federal tax returns (Form 1040)',
        'file_types': ['PDF'],
        'mandatory': True,
        'priority': 3
    },
    'pay_stubs': {
        'name': 'Pay Stubs',
        'description': 'Recent pay stubs or proof of income',
        'file_types': ['PDF', 'JPG', 'PNG'],
        'mandatory': True,
        'priority': 4
    },
    'bank_statements': {
        'name': 'Bank Statements',
        'description': 'Bank statements from the past 3 months',
        'file_types': ['PDF'],
        'mandatory': True,
        'priority': 5
    },
    'drivers_license': {
        'name': 'Driver\'s License',
        'description': 'Copy of driver\'s license or state ID (both front and back)',
        'file_types': ['PDF', 'JPG', 'PNG'],
        'mandatory': True,
        'priority': 6
    },
    'ssn_card': {
        'name': 'Social Security Card',
        'description': 'Copy of Social Security card',
        'file_types': ['PDF', 'JPG', 'PNG'],
        'mandatory': True,
        'priority': 7
    },
    'application_form': {
        'name': 'Application Form',
        'description': 'Completed and signed application form with all disclosures',
        'file_types': ['PDF'],
        'mandatory': True,
        'priority': 8
    }
}


CONVERSATION_STAGES = {
    'GREETING': {
        'stage': 'greeting',
        'description': 'Initial greeting and introduction',
        'order': 1
    },
    'POLICY_EXPLANATION': {
        'stage': 'policy_explanation',
        'description': 'Explaining Silver, Gold, and Platinum policy types',
        'order': 2
    },
    'POLICY_SELECTION': {
        'stage': 'policy_selection',
        'description': 'Customer selecting policy type',
        'order': 3
    },
    'PERSONAL_INFO': {
        'stage': 'personal_info',
        'description': 'Collecting personal information',
        'order': 4,
        'fields': ['full_name', 'dob', 'age', 'phone', 'email', 'address', 'ssn', 'citizenship']
    },
    'POLICY_DETAILS': {
        'stage': 'policy_details',
        'description': 'Collecting policy preference details',
        'order': 5,
        'fields': ['policy_type', 'coverage_amount', 'term', 'beneficiary']
    },
    'FINANCIAL_INFO': {
        'stage': 'financial_info',
        'description': 'Collecting employment and financial information',
        'order': 6,
        'fields': ['occupation', 'employer', 'income', 'net_worth', 'home_ownership']
    },
    'HEALTH_INFO': {
        'stage': 'health_info',
        'description': 'Collecting health and medical history',
        'order': 7,
        'fields': ['height', 'weight', 'tobacco', 'medical_conditions', 'medications']
    },
    'LIFESTYLE_INFO': {
        'stage': 'lifestyle_info',
        'description': 'Collecting lifestyle and behavioral information',
        'order': 8,
        'fields': ['alcohol', 'exercise', 'high_risk_activities', 'travel']
    },
    'DRIVING_INFO': {
        'stage': 'driving_info',
        'description': 'Collecting driving record information',
        'order': 9,
        'fields': ['license', 'violations', 'accidents', 'mileage']
    },
    'ADDITIONAL_INFO': {
        'stage': 'additional_info',
        'description': 'Additional underwriting information',
        'order': 10,
        'fields': ['bankruptcy', 'felony', 'lawsuits', 'previous_applications']
    },
    'DOCUMENT_REQUEST': {
        'stage': 'document_request',
        'description': 'Requesting required documents',
        'order': 11
    },
    'UPLOAD_READY': {
        'stage': 'upload_ready',
        'description': 'Customer ready to upload documents',
        'order': 12
    }
}


EXTRACTION_KEYWORDS = {
    'policy_types': {
        'silver': ['silver', 'basic', 'foundation', 'starter'],
        'gold': ['gold', 'enhanced', 'standard', 'middle'],
        'platinum': ['platinum', 'premium', 'high', 'maximum', 'best']
    },
    'tobacco_use': {
        'yes': ['yes', 'smoke', 'smoker', 'smoking', 'tobacco', 'cigarette', 'cigar', 'vape', 'vaping'],
        'no': ['no', 'never', "don't", 'not', 'quit', 'stopped']
    },
    'alcohol_consumption': {
        'never': ['never', 'no', "don't drink"],
        'occasionally': ['occasionally', 'rarely', 'sometimes', 'social'],
        'moderately': ['moderate', 'moderately', 'regular', 'weekly'],
        'frequently': ['frequently', 'daily', 'heavy', 'often']
    },
    'upload_ready': [
        'ready', 'yes', 'i have', 'upload', 'link', 'send link',
        'all set', 'got them', 'have everything', 'can upload',
        'send me', 'give me the link', 'where do i upload'
    ]
}


def ensure_directories():
    """Create necessary directories if they don't exist"""
    for folder in [LOCAL_CONFIG['UPLOAD_FOLDER'], LOCAL_CONFIG['SESSION_FOLDER']]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            print(f"[CONFIG] Created directory: {folder}")

ensure_directories()