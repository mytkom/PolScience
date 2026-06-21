package org.example;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Getter;
import lombok.Setter;

@JsonIgnoreProperties(ignoreUnknown = true)
@Getter
@Setter
public class InstitutionResponse
{

    private String id;
    private String name;
    private String objectType;
    private InstitutionObject object;
}