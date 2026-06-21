package org.example;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.Setter;

@JsonIgnoreProperties(ignoreUnknown = true)
@Getter
@Setter
public class SupervisingInstitution
{
    private String supervisingInstitutionID;
    private String supervisingInstitutionName;
    private String dateFrom;
}
