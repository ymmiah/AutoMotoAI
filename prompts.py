"""
Prompt templates for AutoMoto AI
"""

def get_task_prompt(task_desc):
    """Generate a confirmation prompt for a task"""
    return f"User requested task: {task_desc}. Should I proceed? (Yes/No)"

def get_analysis_prompt(task_desc):
    """Generate a prompt to analyze and break down a task"""
    return f"""
    Analyze this task and break it down into actionable steps: {task_desc}
    
    Provide:
    1. What actions need to be performed
    2. What applications or tools are needed
    3. Any potential risks or considerations
    4. Step-by-step execution plan
    """

def get_error_prompt(error_msg):
    """Generate a prompt for error handling"""
    return f"An error occurred: {error_msg}. How should I handle this?"

def get_clarification_prompt(task_desc):
    """Generate a prompt when task is unclear"""
    return f"The task '{task_desc}' is unclear. What specific action would you like me to perform?"
