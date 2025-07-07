#!/usr/bin/env python3
"""
Pipeline Detection and Classification System
Detects and classifies different types of bioinformatics pipelines for appropriate validation.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum
import re

class PipelineType(Enum):
    """Types of pipelines we can detect and validate."""
    NEXTFLOW_DSL2_NFCORE = "nextflow_dsl2_nfcore"
    NEXTFLOW_DSL2_CUSTOM = "nextflow_dsl2_custom"
    NEXTFLOW_DSL1 = "nextflow_dsl1"
    NEXTFLOW_MIXED = "nextflow_mixed"
    SNAKEMAKE = "snakemake"
    WDL = "wdl"
    CWL = "cwl"
    SHELL_BASED = "shell_based"
    PYTHON_BASED = "python_based"
    UNKNOWN = "unknown"

class PipelineDetector:
    """Detects and classifies pipeline types for appropriate validation strategies."""
    
    def __init__(self):
        self.detection_patterns = {
            # Nextflow patterns
            'nextflow_config': ['nextflow.config'],
            'nextflow_main': ['main.nf'],
            'nextflow_modules': ['modules/', 'modules/local/', 'modules/nf-core/'],
            'nextflow_subworkflows': ['subworkflows/', 'subworkflows/local/', 'subworkflows/nf-core/'],
            'nextflow_workflows': ['workflows/'],
            'nfcore_structure': ['conf/', 'assets/', 'bin/', 'docs/', 'lib/'],
            
            # Other workflow managers
            'snakemake': ['Snakefile', 'snakemake', 'rules/'],
            'wdl': ['*.wdl'],
            'cwl': ['*.cwl'],
            
            # Traditional/legacy patterns
            'shell_scripts': ['*.sh', 'run*.sh', 'pipeline*.sh'],
            'python_pipeline': ['*pipeline*.py', '*Pipeline*.py'],
            'makefile': ['Makefile', 'makefile'],
        }
    
    def detect_pipeline_type(self, pipeline_path: Path) -> Tuple[PipelineType, Dict[str, any]]:
        """
        Detect the type of pipeline and return classification with metadata.
        
        Returns:
            Tuple of (PipelineType, metadata_dict)
        """
        if not pipeline_path.exists():
            return PipelineType.UNKNOWN, {"error": "Pipeline path does not exist"}
        
        metadata = {
            "path": str(pipeline_path),
            "detected_files": [],
            "structure_analysis": {},
            "dsl_version": None,
            "validation_strategy": None
        }
        
        # Check for Nextflow pipelines
        nextflow_result = self._detect_nextflow_pipeline(pipeline_path, metadata)
        if nextflow_result != PipelineType.UNKNOWN:
            return nextflow_result, metadata
        
        # Check for other workflow managers
        other_wf_result = self._detect_other_workflows(pipeline_path, metadata)
        if other_wf_result != PipelineType.UNKNOWN:
            return other_wf_result, metadata
        
        # Check for traditional/legacy pipelines
        legacy_result = self._detect_legacy_pipeline(pipeline_path, metadata)
        if legacy_result != PipelineType.UNKNOWN:
            return legacy_result, metadata
        
        return PipelineType.UNKNOWN, metadata
    
    def _detect_nextflow_pipeline(self, pipeline_path: Path, metadata: Dict) -> PipelineType:
        """Detect Nextflow pipeline type and DSL version."""
        
        # Look for Nextflow files
        nf_files = list(pipeline_path.rglob('*.nf'))
        config_files = list(pipeline_path.glob('nextflow.config'))
        
        if not nf_files and not config_files:
            return PipelineType.UNKNOWN
        
        metadata["detected_files"].extend([str(f.relative_to(pipeline_path)) for f in nf_files])
        metadata["detected_files"].extend([str(f.relative_to(pipeline_path)) for f in config_files])
        
        # Analyze DSL version
        dsl_version = self._detect_dsl_version(nf_files + config_files)
        metadata["dsl_version"] = dsl_version
        
        # Check for nf-core structure
        is_nfcore = self._is_nfcore_structure(pipeline_path, metadata)
        
        # Classify based on findings
        if dsl_version == "mixed":
            metadata["validation_strategy"] = "mixed_dsl_analysis"
            return PipelineType.NEXTFLOW_MIXED
        elif dsl_version == "DSL1":
            metadata["validation_strategy"] = "dsl1_analysis"
            return PipelineType.NEXTFLOW_DSL1
        elif dsl_version == "DSL2":
            if is_nfcore:
                metadata["validation_strategy"] = "standard_nfcore_validation"
                return PipelineType.NEXTFLOW_DSL2_NFCORE
            else:
                metadata["validation_strategy"] = "custom_dsl2_validation"
                return PipelineType.NEXTFLOW_DSL2_CUSTOM
        
        # Default to custom DSL2 if we found Nextflow files
        metadata["validation_strategy"] = "custom_dsl2_validation"
        return PipelineType.NEXTFLOW_DSL2_CUSTOM
    
    def _detect_dsl_version(self, files: List[Path]) -> str:
        """Detect DSL version from Nextflow files."""
        dsl1_patterns = [
            r'Channel\s*\.',  # DSL1 channel syntax
            r'\.into\s*\(',   # DSL1 into operator
            r'\.set\s*\{',    # DSL1 set operator
            r'process\s+\w+\s*\{[^}]*script:',  # DSL1 process syntax
        ]
        
        dsl2_patterns = [
            r'nextflow\.enable\.dsl\s*=\s*2',
            r'workflow\s+\w*\s*\{',  # DSL2 workflow blocks
            r'include\s+\{',         # DSL2 include syntax
            r'emit:',                # DSL2 emit syntax
        ]
        
        found_dsl1 = False
        found_dsl2 = False
        
        for file_path in files:
            try:
                content = file_path.read_text(encoding='utf-8')
                
                # Check for DSL1 patterns
                for pattern in dsl1_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        found_dsl1 = True
                        break
                
                # Check for DSL2 patterns
                for pattern in dsl2_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        found_dsl2 = True
                        break
                        
            except Exception:
                continue
        
        if found_dsl1 and found_dsl2:
            return "mixed"
        elif found_dsl2:
            return "DSL2"
        elif found_dsl1:
            return "DSL1"
        else:
            return "unknown"
    
    def _is_nfcore_structure(self, pipeline_path: Path, metadata: Dict) -> bool:
        """Check if pipeline follows nf-core structure."""
        nfcore_indicators = [
            'modules/nf-core/',
            'subworkflows/nf-core/',
            'conf/modules.config',
            'assets/',
            '.nf-core.yml'
        ]
        
        structure_score = 0
        found_indicators = []
        
        for indicator in nfcore_indicators:
            if (pipeline_path / indicator).exists():
                structure_score += 1
                found_indicators.append(indicator)
        
        metadata["structure_analysis"]["nfcore_indicators"] = found_indicators
        metadata["structure_analysis"]["nfcore_score"] = structure_score
        
        return structure_score >= 2  # At least 2 indicators for nf-core classification
    
    def _detect_other_workflows(self, pipeline_path: Path, metadata: Dict) -> PipelineType:
        """Detect other workflow management systems."""
        
        # Snakemake
        if (pipeline_path / 'Snakefile').exists() or list(pipeline_path.rglob('*.smk')):
            metadata["validation_strategy"] = "snakemake_analysis"
            return PipelineType.SNAKEMAKE
        
        # WDL
        if list(pipeline_path.rglob('*.wdl')):
            metadata["validation_strategy"] = "wdl_analysis"
            return PipelineType.WDL
        
        # CWL
        if list(pipeline_path.rglob('*.cwl')):
            metadata["validation_strategy"] = "cwl_analysis"
            return PipelineType.CWL
        
        return PipelineType.UNKNOWN
    
    def _detect_legacy_pipeline(self, pipeline_path: Path, metadata: Dict) -> PipelineType:
        """Detect traditional/legacy pipeline types."""
        
        # Look for shell scripts
        shell_scripts = list(pipeline_path.rglob('*.sh'))
        python_scripts = list(pipeline_path.rglob('*pipeline*.py')) + list(pipeline_path.rglob('*Pipeline*.py'))
        
        if shell_scripts:
            metadata["detected_files"].extend([str(f.relative_to(pipeline_path)) for f in shell_scripts[:5]])
            
            # Check if it's primarily shell-based
            main_scripts = [f for f in shell_scripts if any(keyword in f.name.lower() 
                           for keyword in ['run', 'pipeline', 'main', 'execute'])]
            
            if main_scripts:
                metadata["validation_strategy"] = "shell_pipeline_analysis"
                metadata["main_scripts"] = [str(f.relative_to(pipeline_path)) for f in main_scripts]
                return PipelineType.SHELL_BASED
        
        if python_scripts:
            metadata["detected_files"].extend([str(f.relative_to(pipeline_path)) for f in python_scripts[:3]])
            metadata["validation_strategy"] = "python_pipeline_analysis"
            return PipelineType.PYTHON_BASED
        
        return PipelineType.UNKNOWN
    
    def get_validation_recommendations(self, pipeline_type: PipelineType, metadata: Dict) -> Dict[str, any]:
        """Get recommendations for validating the detected pipeline type."""
        
        recommendations = {
            "applicable_rules": [],
            "validation_approach": "",
            "context_strategy": "",
            "special_considerations": []
        }
        
        if pipeline_type == PipelineType.NEXTFLOW_DSL2_NFCORE:
            recommendations.update({
                "applicable_rules": ["ph-core requirements", "ph-core recommendations", "AMDP prerequisites"],
                "validation_approach": "full_nfcore_validation",
                "context_strategy": "smart_hybrid",
                "special_considerations": ["Standard nf-core structure", "All rules applicable"]
            })
        
        elif pipeline_type == PipelineType.NEXTFLOW_DSL2_CUSTOM:
            recommendations.update({
                "applicable_rules": ["ph-core requirements (adapted)", "ph-core recommendations (subset)"],
                "validation_approach": "adapted_nfcore_validation",
                "context_strategy": "full_context_priority",
                "special_considerations": ["Custom structure", "Rule adaptation needed", "Focus on core requirements"]
            })
        
        elif pipeline_type == PipelineType.NEXTFLOW_DSL1:
            recommendations.update({
                "applicable_rules": ["ph-core requirements (DSL1 adapted)", "General best practices"],
                "validation_approach": "dsl1_specific_validation",
                "context_strategy": "full_context",
                "special_considerations": ["DSL1 syntax patterns", "Legacy structure", "Limited rule applicability"]
            })
        
        elif pipeline_type == PipelineType.NEXTFLOW_MIXED:
            recommendations.update({
                "applicable_rules": ["Mixed DSL analysis", "Migration recommendations"],
                "validation_approach": "mixed_dsl_analysis",
                "context_strategy": "comprehensive_analysis",
                "special_considerations": ["DSL migration needed", "Inconsistent patterns", "Modernization recommendations"]
            })
        
        elif pipeline_type in [PipelineType.SHELL_BASED, PipelineType.PYTHON_BASED]:
            recommendations.update({
                "applicable_rules": ["General bioinformatics best practices", "Documentation standards"],
                "validation_approach": "legacy_pipeline_analysis",
                "context_strategy": "script_analysis",
                "special_considerations": ["Legacy pipeline", "Limited rule applicability", "Modernization suggestions"]
            })
        
        else:
            recommendations.update({
                "applicable_rules": ["Basic structure analysis"],
                "validation_approach": "unknown_pipeline_analysis",
                "context_strategy": "exploratory_analysis",
                "special_considerations": ["Unknown pipeline type", "Manual analysis needed"]
            })
        
        return recommendations

if __name__ == "__main__":
    # Test the detector
    detector = PipelineDetector()
    
    # Test with the example pipeline
    test_path = Path("/Users/arunbodd/Documents/Work/Nextflow_pipelines/NCHHSTP-DTBE-Varpipe-WGS")
    if test_path.exists():
        pipeline_type, metadata = detector.detect_pipeline_type(test_path)
        recommendations = detector.get_validation_recommendations(pipeline_type, metadata)
        
        print(f"🔍 Pipeline Detection Results:")
        print(f"   Type: {pipeline_type.value}")
        print(f"   DSL Version: {metadata.get('dsl_version', 'N/A')}")
        print(f"   Validation Strategy: {metadata.get('validation_strategy', 'N/A')}")
        print(f"   Detected Files: {metadata.get('detected_files', [])[:5]}")
        print(f"\n📋 Validation Recommendations:")
        print(f"   Applicable Rules: {recommendations['applicable_rules']}")
        print(f"   Validation Approach: {recommendations['validation_approach']}")
        print(f"   Special Considerations: {recommendations['special_considerations']}")
